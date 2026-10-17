import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_refresh_token
from app.db.models import RefreshToken, User
from tests.conftest import TEST_JWT_SECRET
from tests.integration.helpers import (
    PASSWORD,
    bearer,
    login,
    new_client,
    refresh_with,
    register,
)

pytestmark = pytest.mark.integration


def _refresh_cookie(client: TestClient) -> str:
    value = client.cookies.get("tt_refresh")
    assert value, "refresh cookie not set"
    return value


def _set_cookie_header(response: object) -> str:
    return response.headers["set-cookie"]  # type: ignore[attr-defined, no-any-return]


# --- Registration ---------------------------------------------------------------------------


def test_first_user_is_admin_and_second_is_user(client: TestClient) -> None:
    first = register(client, "first@example.com")
    second = register(client, "second@example.com")
    assert first["role"] == "admin"
    assert second["role"] == "user"
    assert "password" not in first and "password_hash" not in first


def test_register_normalises_email_and_defaults(client: TestClient) -> None:
    user = register(client, "  Alice@Example.COM ")
    assert user["email"] == "alice@example.com"
    assert user["display_name"] == "alice"
    assert user["timezone"] == "UTC"
    assert user["is_active"] is True


def test_register_duplicate_email_is_conflict(client: TestClient) -> None:
    register(client, "dup@example.com")
    response = client.post(
        "/api/v1/auth/register", json={"email": "DUP@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_register_short_password_uses_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "short"}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"]
    assert error["details"]["errors"][0]["loc"] == ["body", "password"]


def test_register_cannot_choose_role(client: TestClient) -> None:
    register(client, "first@example.com")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "sneaky@example.com", "password": PASSWORD, "role": "admin"},
    )
    assert response.status_code == 422


def test_registration_can_be_turned_off(app_factory: Callable[..., FastAPI]) -> None:
    with TestClient(app_factory(allow_registration=False)) as client:
        assert client.get("/api/v1/auth/config").json() == {"allow_registration": False}
        response = client.post(
            "/api/v1/auth/register", json={"email": "a@example.com", "password": PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "registration_disabled"


def test_auth_config_reports_open_registration(client: TestClient) -> None:
    assert client.get("/api/v1/auth/config").json() == {"allow_registration": True}


def test_concurrent_first_registrations_make_exactly_one_admin(app: FastAPI) -> None:
    barrier = threading.Barrier(5)
    roles: list[str] = []

    def worker(index: int) -> None:
        client = new_client(app)
        barrier.wait()
        roles.append(register(client, f"racer{index}@example.com")["role"])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(roles) == ["admin", "user", "user", "user", "user"]


# --- Login ----------------------------------------------------------------------------------


def test_login_returns_access_token_and_refresh_cookie(client: TestClient) -> None:
    register(client, "a@example.com")
    response = client.post(
        "/api/v1/auth/login", json={"email": "A@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert "refresh_token" not in body

    cookie = _set_cookie_header(response).lower()
    assert "tt_refresh=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "max-age=604800" in cookie
    assert "secure" not in cookie  # served over plain http


def test_refresh_cookie_is_secure_when_public_url_is_https(
    app_factory: Callable[..., FastAPI],
) -> None:
    with TestClient(app_factory(public_url="https://tt.example.com")) as client:
        register(client, "a@example.com")
        response = client.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD}
        )
        assert "secure" in _set_cookie_header(response).lower()


@pytest.mark.parametrize(
    ("email", "password"),
    [("a@example.com", "wrong-password"), ("nobody@example.com", PASSWORD)],
)
def test_login_failures_look_the_same(client: TestClient, email: str, password: str) -> None:
    register(client, "a@example.com")
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in response.headers


def test_inactive_user_cannot_log_in(client: TestClient, db_engine: Engine) -> None:
    register(client, "a@example.com")
    with Session(db_engine) as session:
        session.execute(update(User).values(is_active=False))
        session.commit()
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


def test_refresh_tokens_are_stored_hashed(client: TestClient, db_engine: Engine) -> None:
    register(client, "a@example.com")
    login(client, "a@example.com")
    cookie = _refresh_cookie(client)
    with Session(db_engine) as session:
        hashes = session.scalars(select(RefreshToken.token_hash)).all()
    assert len(hashes) == 1
    assert hashes[0] != cookie
    assert cookie not in hashes[0]


# --- Access tokens and /me ------------------------------------------------------------------


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_returns_profile(client: TestClient) -> None:
    register(client, "a@example.com", display_name="Alice")
    token = login(client, "a@example.com")
    response = client.get("/api/v1/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice"
    assert response.json()["role"] == "admin"


def test_expired_access_token_is_rejected(client: TestClient) -> None:
    user_id = register(client, "a@example.com")["id"]
    expired = create_access_token(
        uuid.UUID(user_id), TEST_JWT_SECRET, now=datetime.now(UTC) - timedelta(minutes=16)
    )
    response = client.get("/api/v1/me", headers=bearer(expired.token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_refresh_token_cannot_be_used_as_access_token(client: TestClient) -> None:
    user_id = register(client, "a@example.com")["id"]
    refresh = create_refresh_token(uuid.UUID(user_id), TEST_JWT_SECRET)
    response = client.get("/api/v1/me", headers=bearer(refresh.token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_access_token_of_deactivated_user_is_rejected(
    client: TestClient, db_engine: Engine
) -> None:
    register(client, "a@example.com")
    token = login(client, "a@example.com")
    with Session(db_engine) as session:
        session.execute(update(User).values(is_active=False))
        session.commit()
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


def test_access_token_of_deleted_user_is_rejected(client: TestClient) -> None:
    token = create_access_token(uuid.uuid4(), TEST_JWT_SECRET).token
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 401


# --- Refresh and logout ---------------------------------------------------------------------


def test_expired_access_token_refreshes_silently(client: TestClient) -> None:
    """The flow the frontend follows: 401 token_expired -> POST /auth/refresh -> retry."""
    user_id = register(client, "a@example.com")["id"]
    login(client, "a@example.com")
    expired = create_access_token(
        uuid.UUID(user_id), TEST_JWT_SECRET, now=datetime.now(UTC) - timedelta(minutes=20)
    )
    assert client.get("/api/v1/me", headers=bearer(expired.token)).status_code == 401

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    new_token = refreshed.json()["access_token"]
    assert client.get("/api/v1/me", headers=bearer(new_token)).status_code == 200


def test_refresh_rotates_the_refresh_token(app: FastAPI, client: TestClient) -> None:
    register(client, "a@example.com")
    login(client, "a@example.com")
    old_cookie = _refresh_cookie(client)

    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    new_cookie = _refresh_cookie(client)
    assert new_cookie != old_cookie

    replay = refresh_with(app, old_cookie)
    assert replay.status_code == 401
    assert refresh_with(app, new_cookie).status_code == 200


def _age_revocations(db_engine: Engine, seconds: int) -> None:
    """Pretend every revocation happened `seconds` ago."""
    with Session(db_engine) as session:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.revoked.is_(True))
            .values(revoked_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        session.commit()


def test_parallel_refresh_race_keeps_the_session(app: FastAPI, client: TestClient) -> None:
    """Two tabs refresh with the same cookie: the loser is told to retry, nobody is logged out."""
    register(client, "a@example.com")
    login(client, "a@example.com")
    old_cookie = _refresh_cookie(client)
    assert client.post("/api/v1/auth/refresh").status_code == 200  # tab A wins

    loser = refresh_with(app, old_cookie)  # tab B, a moment later
    assert loser.status_code == 401
    assert loser.json()["error"]["code"] == "refresh_token_superseded"
    assert "set-cookie" not in loser.headers  # must not wipe tab A's new cookie
    assert client.post("/api/v1/auth/refresh").status_code == 200  # session still alive


def test_reused_refresh_token_revokes_every_session(
    app: FastAPI, client: TestClient, db_engine: Engine
) -> None:
    """An old token showing up later was copied: sign the user out everywhere."""
    register(client, "a@example.com")
    other_device = new_client(app)
    login(other_device, "a@example.com")
    login(client, "a@example.com")
    stolen = _refresh_cookie(client)
    assert client.post("/api/v1/auth/refresh").status_code == 200
    _age_revocations(db_engine, seconds=31)

    replay = refresh_with(app, stolen)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"

    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert other_device.post("/api/v1/auth/refresh").status_code == 401
    login(client, "a@example.com")  # logging in again still works


def test_reused_logged_out_token_revokes_every_session(
    app: FastAPI, client: TestClient, db_engine: Engine
) -> None:
    register(client, "a@example.com")
    login(client, "a@example.com")
    cookie = _refresh_cookie(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    other_device = new_client(app)
    login(other_device, "a@example.com")
    _age_revocations(db_engine, seconds=60)

    assert refresh_with(app, cookie).json()["error"]["code"] == "invalid_refresh_token"
    assert other_device.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_rejected_and_clears_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"
    assert 'tt_refresh=""' in _set_cookie_header(response)


def test_refresh_with_forged_cookie_is_rejected(app: FastAPI) -> None:
    assert refresh_with(app, "not-a-jwt").status_code == 401


def test_refresh_with_unknown_but_valid_jwt_is_rejected(app: FastAPI, client: TestClient) -> None:
    user_id = register(client, "a@example.com")["id"]
    unstored = create_refresh_token(uuid.UUID(user_id), TEST_JWT_SECRET)
    assert refresh_with(app, unstored.token).status_code == 401


def test_refresh_rejects_token_expired_in_database(
    app: FastAPI, client: TestClient, db_engine: Engine
) -> None:
    register(client, "a@example.com")
    login(client, "a@example.com")
    with Session(db_engine) as session:
        session.execute(
            update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.commit()
    assert refresh_with(app, _refresh_cookie(client)).status_code == 401


def test_logout_revokes_refresh_token(app: FastAPI, client: TestClient) -> None:
    register(client, "a@example.com")
    login(client, "a@example.com")
    cookie = _refresh_cookie(client)

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert 'tt_refresh=""' in _set_cookie_header(response)
    assert refresh_with(app, cookie).status_code == 401


def test_logout_without_session_is_harmless(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 204


# --- Profile updates ------------------------------------------------------------------------


def test_update_profile(client: TestClient) -> None:
    register(client, "a@example.com")
    token = login(client, "a@example.com")
    response = client.patch(
        "/api/v1/me",
        headers=bearer(token),
        json={"display_name": "  Alice A. ", "timezone": "Europe/Rome"},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice A."
    assert response.json()["timezone"] == "Europe/Rome"
    assert client.get("/api/v1/me", headers=bearer(token)).json()["timezone"] == "Europe/Rome"


def test_update_profile_rejects_invalid_time_zone(client: TestClient) -> None:
    register(client, "a@example.com")
    token = login(client, "a@example.com")
    response = client.patch("/api/v1/me", headers=bearer(token), json={"timezone": "Mars/Base"})
    assert response.status_code == 422


def test_update_profile_cannot_change_role(client: TestClient) -> None:
    register(client, "first@example.com")
    register(client, "b@example.com")
    token = login(client, "b@example.com")
    response = client.patch("/api/v1/me", headers=bearer(token), json={"role": "admin"})
    assert response.status_code == 422
    assert client.get("/api/v1/me", headers=bearer(token)).json()["role"] == "user"


def test_password_change_needs_correct_current_password(client: TestClient) -> None:
    register(client, "a@example.com")
    token = login(client, "a@example.com")
    response = client.patch(
        "/api/v1/me",
        headers=bearer(token),
        json={"current_password": "not-my-password", "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_current_password"
    login(client, "a@example.com")  # old password still works


def test_password_change_signs_out_other_sessions(app: FastAPI, client: TestClient) -> None:
    register(client, "a@example.com")
    other_device = new_client(app)
    login(other_device, "a@example.com")
    other_cookie = _refresh_cookie(other_device)

    token = login(client, "a@example.com")
    response = client.patch(
        "/api/v1/me",
        headers=bearer(token),
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 200

    assert refresh_with(app, other_cookie).status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 200  # this session survives
    login(client, "a@example.com", "a-brand-new-password")
    failed = client.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert failed.status_code == 401
