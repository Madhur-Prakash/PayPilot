"""The RBAC map, password policy, token handling and log redaction."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import InvalidTokenError, TokenExpiredError, ValidationError
from app.core.logging import redact
from app.core.permissions import (
    ALL_PERMISSIONS,
    Permission,
    Role,
    permissions_for_role,
    permissions_for_roles,
)
from app.core.security import (
    create_access_token,
    decode_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_tokens_match,
    validate_password_strength,
    verify_password,
)


class TestRoleMap:
    def test_roles_are_strictly_nested_where_intended(self):
        viewer = permissions_for_role(Role.VIEWER)
        analyst = permissions_for_role(Role.ANALYST)
        admin = permissions_for_role(Role.ADMIN)
        owner = permissions_for_role(Role.OWNER)

        assert viewer < analyst, "an analyst should do everything a viewer can"
        assert analyst < admin, "an admin should do everything an analyst can"
        assert admin < owner, "an owner should do everything an admin can"

    def test_viewer_holds_no_write_permission(self):
        write_actions = {"create", "execute", "approve", "write", "manage", "run"}
        for permission in permissions_for_role(Role.VIEWER):
            action = str(permission).split(":")[1]
            assert action not in write_actions, f"viewer must not hold {permission}"

    def test_analyst_can_propose_but_not_execute(self):
        analyst = permissions_for_role(Role.ANALYST)
        assert Permission.CAMPAIGN_CREATE in analyst
        assert Permission.EXPERIMENT_CREATE in analyst
        assert Permission.CAMPAIGN_EXECUTE not in analyst
        assert Permission.CAMPAIGN_APPROVE not in analyst
        assert Permission.EXPERIMENT_APPROVE not in analyst

    def test_only_owner_manages_users(self):
        for role in (Role.ADMIN, Role.ANALYST, Role.STAFF, Role.VIEWER):
            assert Permission.USERS_MANAGE not in permissions_for_role(role)
        assert Permission.USERS_MANAGE in permissions_for_role(Role.OWNER)

    def test_staff_cannot_reach_growth_recommendations(self):
        staff = permissions_for_role(Role.STAFF)
        assert Permission.GROWTH_RECOMMEND not in staff
        assert Permission.INVENTORY_WRITE in staff

    def test_every_permission_belongs_to_at_least_one_role(self):
        granted = set()
        for role in Role:
            granted |= permissions_for_role(role)
        assert set(ALL_PERMISSIONS) == granted

    def test_unknown_role_grants_nothing(self):
        assert permissions_for_role("SUPERUSER") == frozenset()

    def test_combining_roles_unions_permissions(self):
        combined = permissions_for_roles([Role.VIEWER, Role.ADMIN])
        assert combined == permissions_for_role(Role.ADMIN)


class TestPasswordPolicy:
    def test_a_strong_password_is_accepted(self):
        validate_password_strength("Str0ng&Passw0rd")

    @pytest.mark.parametrize(
        "password",
        ["Sh0rt!a", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsAtAll!", "NoSymbols1234"],
    )
    def test_weak_passwords_are_rejected(self, password):
        with pytest.raises(ValidationError):
            validate_password_strength(password)

    def test_the_error_lists_every_unmet_rule_at_once(self):
        with pytest.raises(ValidationError) as exc:
            validate_password_strength("abc")
        requirements = exc.value.details["requirements"]
        assert len(requirements) >= 3

    def test_hashing_is_salted(self):
        first = hash_password("Str0ng&Passw0rd")
        second = hash_password("Str0ng&Passw0rd")
        assert first != second, "identical passwords must not produce identical hashes"
        assert verify_password("Str0ng&Passw0rd", first)
        assert verify_password("Str0ng&Passw0rd", second)

    def test_verification_rejects_the_wrong_password(self):
        stored = hash_password("Str0ng&Passw0rd")
        assert not verify_password("Str0ng&Passw0rdX", stored)

    def test_a_corrupt_hash_fails_closed(self):
        assert not verify_password("anything", "not-a-real-argon2-hash")


class TestTokens:
    def test_an_access_token_round_trips(self):
        user_id = uuid.uuid4()
        merchant_id = uuid.uuid4()
        token, _expires = create_access_token(
            user_id, merchant_id=merchant_id, roles=[str(Role.ADMIN)]
        )
        payload = decode_token(token)
        assert payload.subject == str(user_id)
        assert payload.merchant_id == str(merchant_id)
        assert payload.roles == (str(Role.ADMIN),)

    def test_an_expired_token_is_rejected(self):
        token, _ = create_access_token(uuid.uuid4(), expires_minutes=-1)
        with pytest.raises(TokenExpiredError):
            decode_token(token)

    def test_a_tampered_token_is_rejected(self):
        token, _ = create_access_token(uuid.uuid4())
        tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
        with pytest.raises(InvalidTokenError):
            decode_token(tampered)

    def test_a_refresh_token_cannot_be_used_as_an_access_token(self):
        token, _ = create_access_token(uuid.uuid4())
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type="refresh")

    def test_refresh_tokens_are_stored_only_as_keyed_hashes(self):
        issued = generate_refresh_token()
        assert issued.token not in issued.token_hash
        assert issued.token_hash == hash_refresh_token(issued.token)
        assert refresh_tokens_match(issued.token, issued.token_hash)
        assert not refresh_tokens_match("some-other-token", issued.token_hash)

    def test_each_refresh_token_is_unique(self):
        tokens = {generate_refresh_token().token for _ in range(50)}
        assert len(tokens) == 50


class TestRedaction:
    def test_secrets_are_removed_from_log_payloads(self):
        cleaned = redact(
            {
                "password": "hunter2",
                "access_token": "eyJ...",
                "api_key": "sk-live-123",
                "merchant_id": "keep-me",
            }
        )
        assert cleaned["password"] == "[redacted]"
        assert cleaned["access_token"] == "[redacted]"
        assert cleaned["api_key"] == "[redacted]"
        assert cleaned["merchant_id"] == "keep-me"

    def test_redaction_reaches_into_nested_structures(self):
        cleaned = redact({"outer": {"items": [{"refresh_token": "abc", "ok": 1}]}})
        assert cleaned["outer"]["items"][0]["refresh_token"] == "[redacted]"
        assert cleaned["outer"]["items"][0]["ok"] == 1

    def test_redaction_is_case_insensitive(self):
        assert redact({"Authorization": "Bearer x"})["Authorization"] == "[redacted]"
