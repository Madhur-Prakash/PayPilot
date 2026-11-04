<div align="center">

# The demo dataset

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Demo script](https://img.shields.io/badge/-Demo_script-64748b?style=flat-square)](DEMO.md)
[![Architecture](https://img.shields.io/badge/-Architecture-2563eb?style=flat-square)](ARCHITECTURE.md)
[![Testing](https://img.shields.io/badge/-Testing-16a34a?style=flat-square)](TESTING.md)

</div>

`Juniper & Oak Coffee`, Portland OR. Fully deterministic from seed `20240917`.

```bash
make seed                          # idempotent
make demo                          # wipe and rebuild
cd backend && python -m app.seed.calibrate   # verify without a database
```

| | |
| --- | --- |
| Products | 8 |
| Customers | 1,700 |
| Transactions | ~14,700 over 180 days |
| Transaction items | ~24,200 |
| Reviews | ~2,475 |
| Competitors | 3, with ~495 seeded reviews |
| Inventory items | 8 |
| External signals | 4 |
| Historical experiments | 2 (one SCALE, one STOP) |

---

## Why it reproduces exactly

Two decisions make the demo stable:

**A fixed RNG seed.** Everything flows from `random.Random(20240917)`.

**A pinned anchor weekday.** The dataset anchors on the most recent *completed
Sunday*, not on "yesterday". Two consecutive 30-day windows contain different
weekday mixes depending on where they start, and with weekend footfall running
~25% above a Tuesday, that alone can swing a period-over-period comparison by
several percent. Pinning the weekday removes it.

---

## The business story is discoverable, not asserted

This is the part that matters. **No code anywhere says "the answer is waiting
time."** The generator creates mechanisms; the analytics layer finds their
consequences.

### 1 · Customers have shape, not uniformity

```python
LOYALTY_TIERS = {          # share of base, visits/week, basket bias
    "CORE":       (0.055, 3.97, 1.14),   # near-daily regulars
    "REGULAR":    (0.035, 1.17, 1.04),
    "OCCASIONAL": (0.150, 0.20, 0.96),
    "RARE":       (0.760, 0.047, 0.90),  # the long tail
}
```

A café's repeat rate is only realistic when a small core of regulars sits on top
of a long tail of infrequent visitors. A small, uniformly-loyal base produces a
~85% repeat rate, which is not a useful signal. This shape produces ~38%.

### 2 · Evening regulars actually churn

```python
EVENING_REGULAR_CHURN_PROB = 0.37
CHURNED_RESIDUAL_RATE      = 0.06
```

37% of habitual evening regulars stop coming, on **staggered days** beginning just
before the current window. Staggering matters: a cliff on one day would read as an
outage, whereas a steady bleed is what an eroding experience actually looks like.

This is real churn, not a uniform dip — which is what makes "recover lost evening
repeat customers" a genuinely recoverable opportunity.

### 3 · Evening baskets shrink

```python
EVENING_COMBO_ATTACH_DECAY = 0.28
```

The attach rate for evening combo items collapses across the window. That is what
drives AOV down, independently of order count.

### 4 · Service degrades, and reviews follow

```python
EVENING_SERVICE_DRIFT_MINUTES = 6.4
```

Evening service time drifts up across the window. Then — and this is the key
mechanism — **reviews are generated from the orders they describe**:

```python
wait_excess = max(wait - WAIT_COMPLAINT_THRESHOLD_MINUTES, 0.0)
complain_p  = min(BASE_COMPLAINT_PROB + wait_excess * WAIT_COMPLAINT_SLOPE, 0.86)
```

The complaint *rate* is never set. As evening service times cross the threshold,
more of those orders produce a waiting-time complaint on their own. The
correlation the Growth Scientist finds is therefore real.

### 5 · Competitors are perceived as faster

Each competitor has a `speed` perception score; a review about waiting time is
positive with probability `speed_score / 100`. A rival at 86 gets praised for
speed; the merchant, whose score is computed from its own reviews, does not.

---

## What comes out

Measured by `python -m app.seed.calibrate`, last 30 days vs the previous 30:

| Metric | Current | Previous | Change |
| --- | --- | --- | --- |
| Revenue | $24,693 | $28,124 | **−12.2%** |
| Orders | 2,353 | 2,473 | −4.9% |
| AOV | $10.49 | $11.37 | −7.7% |
| Repeat rate | 38.3% | 41.4% | −7.7% |
| Avg service time | 7.43 min | 6.97 min | +6.6% |

By trading slot:

| Slot | Revenue change | Service time change |
| --- | --- | --- |
| Morning | −3.1% | −0.4% |
| Afternoon | +0.1% | −1.8% |
| **Evening** | **−31.9%** | **+24.5%** |
| Night | +2.3% | −2.4% |

Reviews, evening slot only:

| | Previous | Current |
| --- | --- | --- |
| Waiting-time complaints | 11 | 21 |
| Negative share | 6.2% | **22.2%** |

Every one of these is *measured from the generated ledger*, not configured.

> The brief's illustrative figures ($9.2K revenue, 2,341 orders, $14.35 AOV) are
> not internally consistent — 2,341 × $14.35 is $33.5K, not $9.2K. The dataset holds
> `revenue = orders × AOV` instead, because the Growth Graph presents that
> relationship as arithmetic and a test asserts it. Order count lands within 0.5%
> of the brief; the direction and magnitude of every movement match.

---

## The experiments

Both are measured by the **ordinary measurement service** — synthetic transactions
are written for each arm, tagged with the experiment and variant, and then
aggregated exactly as live traffic would be. No result is typed in, which is why
the numbers on screen always reconcile with the ledger.

| Experiment | Control | Test | Lift | p | Decision |
| --- | --- | --- | --- | --- | --- |
| Weekend Brunch Combo | 9.35% | 13.85% | +48.1% | 0.038 | **SCALE** |
| Loyalty Chai Pass | 15.13% | 12.33% | −18.5% | 0.321 | **STOP** |

The STOP case is deliberate. A system that measures its own recommendations has to
be able to say no.

### Converter selection is exact, not sampled

With a few hundred customers per arm, Bernoulli sampling noise swamps the effect:
an intended +30% lift routinely realises as anything between −5% and +50%. The
generator takes exactly `round(n × rate)` customers, ordered by a hash of
`experiment:variant:customer`, so assignment is deterministic and unbiased.

### Live experiments in the demo

When you approve an opportunity on a **demo tenant**, the system writes the
transactions the experiment would have produced, from a declared ground truth
(control 8.8%, test ×1.62, baskets ×1.18). Every row carries
`metadata_json.simulated = true`.

The measurement service is not told any of that. It aggregates the rows and
computes conversion, lift, incremental revenue, ROI and significance the same way
it would for live traffic — so the result on screen is genuinely measured.

---

## Team accounts

One per role, so the RBAC story can be demonstrated rather than described.

| Name | Email | Role |
| --- | --- | --- |
| Morgan Hayes | `owner@juniperoak.com` | OWNER |
| Jordan Ellis | `admin@juniperoak.com` | ADMIN |
| Avery Chen | `analyst@juniperoak.com` | ANALYST |
| Sam Rivera | `staff@juniperoak.com` | STAFF |
| Taylor Brooks | `viewer@juniperoak.com` | VIEWER |

Password: `Autopilot@2024`

---

## Retuning it

Constants live at the top of
[`app/seed/generators/dataset.py`](../backend/app/seed/generators/dataset.py).

```bash
cd backend
python -m app.seed.calibrate      # measure without touching the database
```

The harness prints exactly what the dashboard will show. Use it before re-seeding
— a full seed takes ~45 seconds, the harness takes three.

One warning from experience: the generated metrics are **stochastic**, and a small
parameter change shifts the whole RNG stream downstream. Adjacent configurations
can differ by several percent for reasons that have nothing to do with the
parameter. Tune against the fixed seed and read the realised numbers; do not
assume a change had the effect you intended.

---

## Provenance

Everything here is fictional demo data, and the product says so:

- `merchants.is_demo` and `data_source = SEEDED`
- `reviews.is_simulated`, `competitor_reviews.is_simulated`,
  `external_signals.is_simulated`
- `campaigns.is_simulated`, `experiments.is_simulated`
- `ProvenanceMeta` on every relevant API response
- "Demo Simulation" badges in the sidebar, dashboard header, campaigns,
  experiments and competitors

No claim is made anywhere of live PayPal transaction access, real customer
messaging, or competitor-platform scraping.

---

<div align="center">

[Docs index](README.md) · [Demo script](DEMO.md) · [Architecture](ARCHITECTURE.md) ·
[Testing](TESTING.md) · [Contributing](CONTRIBUTING.md)

</div>
