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


class BoardKind(StrEnum):
    """The work item tracker a board connection talks to."""

    AZURE = "azure"
    PLANKA = "planka"


class BoardConnection(OwnedModel):
    """A connection to a board: an Azure DevOps project or a Planka board."""

    __tablename__ = "board_connections"
    __table_args__ = (
        *ownership_constraints("board_connections"),
        CheckConstraint("kind IN ('azure', 'planka')", name="kind_valid"),
    )

    kind: Mapped[str] = mapped_column(String(16), default=BoardKind.AZURE, server_default="azure")
    # Azure: the organization URL (https://dev.azure.com/acme). Planka: the server URL.
    url: Mapped[str] = mapped_column(String(2048))
    # Azure: the project name. Planka: the board ID.
    scope: Mapped[str] = mapped_column(String(255))
    # Fernet ciphertext of the PAT (Azure) or API key (Planka); never returned by the API.
    secret_enc: Mapped[str] = mapped_column(Text)
    last_test_at: Mapped[datetime | None]
    last_test_ok: Mapped[bool | None]
