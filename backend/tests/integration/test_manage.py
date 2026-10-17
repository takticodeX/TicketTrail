"""manage.py rotate-keys against a real database."""

from collections.abc import Callable

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import Settings
from app.core.crypto import SecretBox
from app.manage import rotate_keys
from tests.integration.helpers import (
    AZURE_PAT,
    GIT_TOKEN,
    azure_payload,
    create,
    git_payload,
    signed_in,
)


def stored(db_engine: Engine) -> tuple[str, str]:
    with db_engine.connect() as conn:
        git = conn.execute(text("SELECT secret_enc FROM git_connections")).scalar_one()
        azure = conn.execute(text("SELECT pat_enc FROM azure_connections")).scalar_one()
    return git, azure


def test_rotate_keys_re_encrypts_every_secret(
    app_factory: Callable[..., object], db_engine: Engine, make_settings: Callable[..., Settings]
) -> None:
    old_key = Fernet.generate_key().decode()
    app = app_factory(encryption_key=old_key)
    with TestClient(app) as client:  # type: ignore[arg-type]
        headers = signed_in(client, "admin@example.com")
        create(client, "git-connections", headers, git_payload())
        create(client, "azure-connections", headers, azure_payload())

    new_key = Fernet.generate_key().decode()
    box = SecretBox(new_key, old_key)
    with app.state.session_factory() as db:  # type: ignore[attr-defined]
        assert rotate_keys(db, box) == (2, [])

    git, azure = stored(db_engine)
    only_new = SecretBox(new_key)
    assert only_new.decrypt(git) == GIT_TOKEN
    assert only_new.decrypt(azure) == AZURE_PAT


def test_rotate_keys_reports_undecryptable_secrets(
    app_factory: Callable[..., object], db_engine: Engine
) -> None:
    app = app_factory()
    with TestClient(app) as client:  # type: ignore[arg-type]
        headers = signed_in(client, "admin@example.com")
        create(client, "git-connections", headers, git_payload())
    unrelated = SecretBox(Fernet.generate_key().decode())
    with app.state.session_factory() as db:  # type: ignore[attr-defined]
        rotated, failed = rotate_keys(db, unrelated)
    assert rotated == 0
    assert len(failed) == 1
    assert "App repo" in failed[0]
