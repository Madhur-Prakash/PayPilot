"""Experiment statistics and the decision rule.

These are pure functions, so they are tested directly - no database, no HTTP.
Getting these wrong would mean the product confidently recommends the wrong thing.
"""

from __future__ import annotations

import pytest

from app.db.models.experiment import ExperimentDecision
from app.services.experiments.service import (
    ExperimentService,
    _relative_change,
    two_proportion_p_value,
)


class TestTwoProportionTest:
    def test_identical_proportions_give_p_of_one(self):
        assert two_proportion_p_value(10, 100, 10, 100) == pytest.approx(1.0, abs=1e-6)

    def test_a_large_clear_difference_is_significant(self):
        p = two_proportion_p_value(50, 1000, 120, 1000)
        assert p is not None and p < 0.001

    def test_a_small_sample_is_not_significant(self):
        p = two_proportion_p_value(2, 20, 4, 20)
        assert p is not None and p > 0.05

    def test_groups_too_small_return_none(self):
        """Better to say "not enough data" than to print a meaningless p-value."""
        assert two_proportion_p_value(1, 4, 2, 4) is None

    def test_zero_conversions_everywhere_returns_none(self):
        assert two_proportion_p_value(0, 100, 0, 100) is None

    def test_the_test_is_two_sided(self):
        up = two_proportion_p_value(50, 500, 80, 500)
        down = two_proportion_p_value(80, 500, 50, 500)
        assert up == pytest.approx(down)

    def test_matches_a_hand_computed_z(self):
        # p1=0.10, p2=0.15, n=400 each. pooled=0.125
        # se = sqrt(0.125*0.875*(2/400)) = 0.023385
        # z  = 0.05 / 0.023385 = 2.1381 -> two-sided p ~= 0.0325
        p = two_proportion_p_value(40, 400, 60, 400)
        assert p == pytest.approx(0.0325, abs=0.002)


class TestRelativeChange:
    def test_positive_change(self):
        assert _relative_change(12.5, 10.0) == pytest.approx(25.0)

    def test_negative_change(self):
        assert _relative_change(8.0, 10.0) == pytest.approx(-20.0)

    def test_zero_baseline_is_undefined_not_infinite(self):
        assert _relative_change(5.0, 0.0) is None


class TestDecisionRule:
    """SCALE only when the lift is material, positive-value *and* significant."""

    def test_scale_requires_all_three(self):
        decision, rationale = ExperimentService.decide(
            conversion_lift_pct=42.0,
            incremental_revenue=9840.0,
            roi=4.2,
            p_value=0.01,
            is_significant=True,
            threshold_pct=10.0,
            control_size=300,
            test_size=300,
        )
        assert decision == ExperimentDecision.SCALE
        assert "significant" in rationale.lower()

    def test_promising_but_not_significant_is_continue(self):
        decision, rationale = ExperimentService.decide(
            conversion_lift_pct=42.0,
            incremental_revenue=9840.0,
            roi=4.2,
            p_value=0.21,
            is_significant=False,
            threshold_pct=10.0,
            control_size=300,
            test_size=300,
        )
        assert decision == ExperimentDecision.CONTINUE
        assert "not yet statistically significant" in rationale.lower()

    def test_a_losing_arm_is_stopped(self):
        decision, rationale = ExperimentService.decide(
            conversion_lift_pct=-18.0,
            incremental_revenue=-500.0,
            roi=-0.3,
            p_value=0.3,
            is_significant=False,
            threshold_pct=10.0,
            control_size=300,
            test_size=300,
        )
        assert decision == ExperimentDecision.STOP
        assert "underperformed" in rationale.lower()

    def test_negative_incremental_revenue_stops_even_with_positive_lift(self):
        decision, _ = ExperimentService.decide(
            conversion_lift_pct=3.0,
            incremental_revenue=-1200.0,
            roi=None,
            p_value=0.4,
            is_significant=False,
            threshold_pct=10.0,
            control_size=300,
            test_size=300,
        )
        assert decision == ExperimentDecision.STOP

    def test_below_threshold_is_watch(self):
        decision, _ = ExperimentService.decide(
            conversion_lift_pct=3.0,
            incremental_revenue=200.0,
            roi=1.1,
            p_value=0.6,
            is_significant=False,
            threshold_pct=10.0,
            control_size=300,
            test_size=300,
        )
        assert decision == ExperimentDecision.WATCH

    def test_tiny_groups_are_unreadable_regardless_of_lift(self):
        """A huge lift on 5 customers is noise, and the rule must say so."""
        decision, rationale = ExperimentService.decide(
            conversion_lift_pct=200.0,
            incremental_revenue=5000.0,
            roi=9.0,
            p_value=0.001,
            is_significant=True,
            threshold_pct=10.0,
            control_size=5,
            test_size=5,
        )
        assert decision == ExperimentDecision.CONTINUE
        assert "too small" in rationale.lower()


class TestDeterministicSplit:
    def test_split_is_stable_across_calls(self):
        import uuid

        members = [uuid.uuid4() for _ in range(400)]
        first = ExperimentService._split(members, 50.0)
        second = ExperimentService._split(members, 50.0)
        assert first == second

    def test_split_is_roughly_balanced(self):
        import uuid

        members = [uuid.uuid4() for _ in range(2000)]
        control, test = ExperimentService._split(members, 50.0)
        assert len(control) + len(test) == 2000
        # Hash-bucketed, so expect close to even but not exactly.
        assert abs(len(control) - len(test)) < 200

    def test_split_honours_an_uneven_allocation(self):
        import uuid

        members = [uuid.uuid4() for _ in range(2000)]
        control, test = ExperimentService._split(members, 20.0)
        assert 300 < len(control) < 500
        assert len(test) > len(control)

    def test_ordering_does_not_change_assignment(self):
        """Assignment must depend on the customer, not on list position."""
        import uuid

        members = [uuid.uuid4() for _ in range(500)]
        control_a, _ = ExperimentService._split(members, 50.0)
        control_b, _ = ExperimentService._split(list(reversed(members)), 50.0)
        assert set(control_a) == set(control_b)
