import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    TokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)

SECRET = "unit-test-secret-that-is-long-enough-012345"


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong password!")


def test_verify_password_rejects_garbage_hash() -> None:
    assert not verify_password("not-a-hash", "anything")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    issued = create_access_token(user_id, SECRET)
    assert decode_token(issued.token, SECRET, "access") == user_id


def test_token_lifetimes_match_spec() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert create_access_token(uuid.uuid4(), SECRET, now=now).expires_at == now + timedelta(
        minutes=15
    )
    assert create_refresh_token(uuid.uuid4(), SECRET, now=now).expires_at == now + timedelta(days=7)
    assert timedelta(minutes=15) == ACCESS_TOKEN_TTL
    assert timedelta(days=7) == REFRESH_TOKEN_TTL


def test_expired_token_raises_expired() -> None:
    issued = create_access_token(uuid.uuid4(), SECRET, now=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(TokenExpiredError):
        decode_token(issued.token, SECRET, "access")


def test_refresh_token_is_not_accepted_as_access_token() -> None:
    issued = create_refresh_token(uuid.uuid4(), SECRET)
    with pytest.raises(TokenError):
        decode_token(issued.token, SECRET, "access")


def test_token_signed_with_other_secret_is_rejected() -> None:
    issued = create_access_token(uuid.uuid4(), "another-secret-that-is-long-enough-9876543")
    with pytest.raises(TokenError):
        decode_token(issued.token, SECRET, "access")


def test_unsigned_token_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 0, "exp": 9_999_999_999},
        key=None,
        algorithm="none",
    )
    with pytest.raises(TokenError):
        decode_token(forged, SECRET, "access")


def test_token_without_subject_claims_is_rejected() -> None:
    token = jwt.encode({"type": "access", "exp": 9_999_999_999}, SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_token(token, SECRET, "access")


def test_two_tokens_for_same_user_differ() -> None:
    user_id = uuid.uuid4()
    assert (
        create_refresh_token(user_id, SECRET).token != create_refresh_token(user_id, SECRET).token
    )


def test_hash_token_is_sha256_hex() -> None:
    digest = hash_token("abc")
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
