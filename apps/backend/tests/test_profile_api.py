from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app

_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "a brand new passphrase"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_token(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": "timi@example.com", "displayName": "Timi", "password": _PASSWORD},
    )
    assert response.status_code == 201
    return str(response.json()["data"]["accessToken"])


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "profile-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


@pytest.mark.asyncio
async def test_update_profile_changes_display_name_and_me_reflects_it(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/auth/profile",
            json={"displayName": "  提米二号  "},
            headers=_auth_headers(token),
        )
        me_response = await client.get("/auth/me", headers=_auth_headers(token))

    assert response.status_code == 200
    assert response.json()["data"]["displayName"] == "提米二号"
    assert response.json()["data"]["email"] == "timi@example.com"
    assert me_response.json()["data"]["displayName"] == "提米二号"


@pytest.mark.asyncio
async def test_update_profile_rejects_blank_display_name(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        empty_response = await client.put(
            "/auth/profile",
            json={"displayName": ""},
            headers=_auth_headers(token),
        )
        blank_response = await client.put(
            "/auth/profile",
            json={"displayName": "   "},
            headers=_auth_headers(token),
        )
        anonymous_response = await client.put("/auth/profile", json={"displayName": "x"})

    assert empty_response.status_code == 400
    assert empty_response.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
    assert blank_response.status_code == 422
    assert blank_response.json()["error"]["code"] == "VALIDATION_MISSING_FIELD"
    assert anonymous_response.status_code == 401
    assert anonymous_response.json()["error"]["code"] == "AUTH_UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/auth/password",
            json={"currentPassword": "not the password", "newPassword": _NEW_PASSWORD},
            headers=_auth_headers(token),
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_PASSWORD_MISMATCH"


@pytest.mark.asyncio
async def test_change_password_rejects_short_new_password(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/auth/password",
            json={"currentPassword": _PASSWORD, "newPassword": "short"},
            headers=_auth_headers(token),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_change_password_revokes_all_sessions_and_new_password_logs_in(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        second_token = (
            await client.post(
                "/auth/login",
                json={"email": "timi@example.com", "password": _PASSWORD},
            )
        ).json()["data"]["accessToken"]

        change_response = await client.put(
            "/auth/password",
            json={"currentPassword": _PASSWORD, "newPassword": _NEW_PASSWORD},
            headers=_auth_headers(token),
        )
        assert change_response.status_code == 200
        assert change_response.json()["data"] == {"changed": True}

        # 两个旧会话都必须被吊销。
        for old_token in (token, second_token):
            revoked = await client.get("/auth/me", headers=_auth_headers(old_token))
            assert revoked.status_code == 401
            assert revoked.json()["error"]["code"] == "AUTH_SESSION_REVOKED"

        old_login = await client.post(
            "/auth/login",
            json={"email": "timi@example.com", "password": _PASSWORD},
        )
        assert old_login.status_code == 401

        new_login = await client.post(
            "/auth/login",
            json={"email": "timi@example.com", "password": _NEW_PASSWORD},
        )
        assert new_login.status_code == 200
        assert new_login.json()["data"]["accessToken"]
