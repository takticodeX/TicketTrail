"""Milestone 7 security rules: login rate limits and CSRF protection (spec section 10)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis

from tests.integration.helpers import PASSWORD, register

pytestmark = pytest.mark.integration


def attempt(client: TestClient, email: str, password: str = "wrong-password", ip: str = "") -> int:
    headers = {"X-Forwarded-For": ip} if ip else {}
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )
    return response.status_code


def test_five_login_attempts_a_minute_per_email(client: TestClient, redis: Redis) -> None:
    register(client, "a@example.com")
    assert [attempt(client, "a@example.com") for _ in range(5)] == [401] * 5
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert response.status_code == 429  # even the right password, until the minute is over
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert 0 < int(response.headers["retry-after"]) <= 60


def test_the_limit_is_also_per_address(client: TestClient, redis: Redis) -> None:
    # TestClient's address is "testclient"; different emails, same address.
    codes = [attempt(client, f"user{i}@example.com") for i in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


def test_the_limit_resets(client: TestClient, redis: Redis) -> None:
    register(client, "a@example.com")
    for _ in range(5):
        attempt(client, "a@example.com")
    redis.flushdb()  # as if the minute had passed
    assert attempt(client, "a@example.com", PASSWORD) == 200


def test_logins_still_work_when_redis_is_down(app_factory: object) -> None:
    from app.core.ratelimit import LoginRateLimiter

    app: FastAPI = app_factory()  # type: ignore[operator]
    app.state.login_limiter = LoginRateLimiter(Redis(host="127.0.0.1", port=1, socket_timeout=0.2))
    with TestClient(app) as client:
        register(client, "a@example.com")
        assert attempt(client, "a@example.com", PASSWORD) == 200


@pytest.mark.parametrize("path", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
def test_cookie_endpoints_need_the_csrf_header(app: FastAPI, path: str) -> None:
    bare = TestClient(app)  # a cross-site form post can't add custom headers
    response = bare.post(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_login_does_not_need_the_csrf_header(app: FastAPI) -> None:
    bare = TestClient(app)
    register(bare, "a@example.com")
    response = bare.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
