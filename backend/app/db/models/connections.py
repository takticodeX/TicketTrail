from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedModel, ownership_constraints


class GitAuthType(StrEnum):
    TOKEN = "token"  # noqa: S105  (an auth method name, not a secret)
    BASIC = "basic"
    NONE = "none"


class GitConnection(OwnedModel):
    __tablename__ = "git_connections"
    __table_args__ = (
        *ownership_constraints("git_connections"),
        CheckConstraint("auth_type IN ('token', 'basic', 'none')", name="auth_type_valid"),
    )

    repo_url: Mapped[str] = mapped_column(String(2048))
    auth_type: Mapped[str] = mapped_column(String(16))
    username: Mapped[str | None] = mapped_column(String(255))
    # Fernet ciphertext of the token or password; never returned by the API.
    secret_enc: Mapped[str | None] = mapped_column(Text)
    commit_url_template: Mapped[str | None] = mapped_column(String(2048))
    last_test_at: Mapped[datetime | None]
    last_test_ok: Mapped[bool | None]


class AzureConnection(OwnedModel):
    __tablename__ = "azure_connections"
    __table_args__ = ownership_constraints("azure_connections")

    organization_url: Mapped[str] = mapped_column(String(2048))
    azure_project: Mapped[str] = mapped_column(String(255))
    # Fernet ciphertext of the PAT; never returned by the API.
    pat_enc: Mapped[str] = mapped_column(Text)
    last_test_at: Mapped[datetime | None]
    last_test_ok: Mapped[bool | None]
