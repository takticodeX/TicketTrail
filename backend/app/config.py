"""Application settings loaded from TT_* environment variables."""

import logging
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://tt:tt@db:5432/tickettrail"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TT_", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = "redis://redis:6379/0"
    encryption_key: SecretStr
    jwt_secret: SecretStr
    allow_registration: bool = True
    allow_private_hosts: bool = False
    git_timeout: int = Field(default=300, gt=0)
    min_schedule_minutes: int = Field(default=5, ge=1)
    azure_max_concurrency: int = Field(default=5, ge=1)
    log_level: str = "INFO"
    public_url: str = "http://localhost:8080"

    @field_validator("encryption_key")
    @classmethod
    def _check_fernet_key(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value())
        except ValueError as exc:
            raise ValueError(
                "must be a Fernet key: 32 random bytes, url-safe base64 encoded"
            ) from exc
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _check_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_JWT_SECRET_LENGTH} characters long")
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level {value!r}")
        return level

    @property
    def secure_cookies(self) -> bool:
        """Cookies get the Secure flag only when the app is served over HTTPS."""
        return self.public_url.lower().startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
