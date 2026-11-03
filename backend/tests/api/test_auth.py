"""Authentication: registration, sessions, rotation and password policy."""

from __future__ import annotations

import pytest

from tests.conftest import TEST_PASSWORD


class TestLogin:
    async def test_valid_credentials_return_a_session(self, client):
        response = await client.post(
            "/auth/login", json={"email": "owner@test.in", "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["tokens"]["access_token"]
        assert body["data"]["user"]["role"] == "OWNER"
        assert body["data"]["user"]["active_merchant"]["name"] == "Test Cafe"

    async def test_wrong_password_is_rejected(self, client):
        response = await client.post(
            "/auth/login", json={"email": "owner@test.in", "password": "not-the-password"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_unknown_email_gives_the_same_error(self, client):
        """The response must not reveal whether an address is registered."""
        response = await client.post(
            "/auth/login", json={"email": "nobody@nowhere.in", "password": TEST_PASSWORD}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_refresh_token_is_set_as_an_httponly_cookie(self, client):
        response = await client.post(
            "/auth/login", json={"email": "owner@test.in", "password": TEST_PASSWORD}
        )
        cookie = response.headers.get("set-cookie", "")
        assert "pga_refresh=" in cookie
        assert "HttpOnly" in cookie


class TestProtectedRoutes:
    async def test_dashboard_requires_authentication(self, client):
        response = await client.get("/dashboard/overview")
        assert response.status_code == 401

    async def test_malformed_token_is_rejected(self, client):
        response = await client.get(
            "/dashboard/overview", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    async def test_me_returns_permissions(self, client, owner_headers):
        response = await client.get("/auth/me", headers=owner_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert "dashboard:read" in data["permissions"]
        assert "users:manage" in data["permissions"]


class TestSessionRotation:
    async def test_refresh_rotates_and_the_old_token_is_revoked(self, client):
        login = await client.post(
            "/auth/login", json={"email": "admin@test.in", "password": TEST_PASSWORD}
        )
        original = login.json()["data"]["tokens"]["refresh_token"]

        rotated = await client.post("/auth/refresh", json={"refresh_token": original})
        assert rotated.status_code == 200
        replacement = rotated.json()["data"]["tokens"]["refresh_token"]
        assert replacement != original

        # Replaying the original is treated as a compromise, not a retry.
        replay = await client.post("/auth/refresh", json={"refresh_token": original})
        assert replay.status_code == 401

    async def test_token_reuse_revokes_the_whole_family(self, client):
        login = await client.post(
            "/auth/login", json={"email": "staff@test.in", "password": TEST_PASSWORD}
        )
        first = login.json()["data"]["tokens"]["refresh_token"]

        rotated = await client.post("/auth/refresh", json={"refresh_token": first})
        second = rotated.json()["data"]["tokens"]["refresh_token"]

        # Replay the retired token: this should kill the whole chain...
        await client.post("/auth/refresh", json={"refresh_token": first})
        # ...including the currently-valid successor.
        after = await client.post("/auth/refresh", json={"refresh_token": second})
        assert after.status_code == 401


class TestRegistration:
    async def test_registration_creates_an_owned_workspace(self, client):
        response = await client.post(
            "/auth/register",
            json={
                "email": "founder@newshop.in",
                "password": "BrandNewPass1!",
                "full_name": "New Founder",
                "merchant_name": "New Shop",
            },
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["user"]["role"] == "OWNER"
        assert data["user"]["active_merchant"]["name"] == "New Shop"

    async def test_duplicate_email_is_rejected(self, client):
        response = await client.post(
            "/auth/register",
            json={
                "email": "owner@test.in",
                "password": "AnotherPass1!",
                "full_name": "Impostor",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    @pytest.mark.parametrize(
        "password",
        ["short1!A", "nouppercase1!", "NOLOWERCASE1!", "NoDigitsHere!", "NoSymbols123"],
    )
    async def test_weak_passwords_are_rejected(self, client, password):
        response = await client.post(
            "/auth/register",
            json={
                "email": f"weak-{password[:4]}@test.in",
                "password": password,
                "full_name": "Weak Password",
            },
        )
        assert response.status_code == 422


class TestLogout:
    async def test_logout_revokes_the_refresh_token(self, client):
        login = await client.post(
            "/auth/login", json={"email": "viewer@test.in", "password": TEST_PASSWORD}
        )
        tokens = login.json()["data"]["tokens"]
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        logout = await client.post(
            "/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
        )
        assert logout.status_code == 200

        after = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert after.status_code == 401
