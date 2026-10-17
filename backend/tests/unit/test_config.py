from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_match_spec(make_settings: Callable[..., Settings]) -> None:
    settings = Settings(encryption_key=make_settings().encryption_key, jwt_secret="x" * 32)
    assert settings.database_url == "postgresql+psycopg://tt:tt@db:5432/tickettrail"
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.allow_registration is True
    assert settings.allow_private_hosts is False
    assert settings.git_timeout == 300
    assert settings.min_schedule_minutes == 5
    assert settings.azure_max_concurrency == 5
    assert settings.log_level == "INFO"
    assert settings.public_url == "http://localhost:8080"


def test_reads_tt_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("TT_ENCRYPTION_KEY", make_settings().encryption_key.get_secret_value())
    monkeypatch.setenv("TT_JWT_SECRET", "y" * 40)
    monkeypatch.setenv("TT_ALLOW_REGISTRATION", "false")
    monkeypatch.setenv("TT_LOG_LEVEL", "debug")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.allow_registration is False
    assert settings.log_level == "DEBUG"


def test_encryption_key_and_jwt_secret_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TT_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("TT_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings()  # type: ignore[call-arg]
    fields = {err["loc"][0] for err in exc.value.errors()}
    assert fields == {"encryption_key", "jwt_secret"}


def test_rejects_invalid_fernet_key(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="Fernet key"):
        make_settings(encryption_key="change-me")


def test_rejects_short_jwt_secret(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(jwt_secret="short")


def test_rejects_unknown_log_level(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="LOUD")


@pytest.mark.parametrize(
    ("public_url", "secure"),
    [("http://localhost:8080", False), ("https://tt.example.com", True), ("HTTPS://x.io", True)],
)
def test_secure_cookies_follow_public_url_scheme(
    make_settings: Callable[..., Settings], public_url: str, secure: bool
) -> None:
    assert make_settings(public_url=public_url).secure_cookies is secure


def test_secrets_are_not_shown_in_repr(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.jwt_secret.get_secret_value() not in repr(settings)
    assert settings.encryption_key.get_secret_value() not in repr(settings)
