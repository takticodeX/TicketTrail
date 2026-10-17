"""Password hashing (Argon2id) and JWT access / refresh tokens (HS256)."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)
JWT_ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()  # Argon2id with the library's recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("tickettrail-dummy-password")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so unknown emails can't be detected by timing."""
    verify_password(_dummy_hash(), password)


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


class TokenError(Exception):
    """The token is malformed, has a bad signature or is of the wrong type."""


class TokenExpiredError(TokenError):
    pass


def _issue(
    user_id: uuid.UUID, secret: str, token_type: TokenType, ttl: timedelta, now: datetime | None
) -> IssuedToken:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": issued_at,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    return IssuedToken(jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), expires_at)


def create_access_token(
    user_id: uuid.UUID, secret: str, *, now: datetime | None = None
) -> IssuedToken:
    return _issue(user_id, secret, "access", ACCESS_TOKEN_TTL, now)


def create_refresh_token(
    user_id: uuid.UUID, secret: str, *, now: datetime | None = None
) -> IssuedToken:
    return _issue(user_id, secret, "refresh", REFRESH_TOKEN_TTL, now)


def decode_token(token: str, secret: str, expected_type: TokenType) -> uuid.UUID:
    """Validate a token and return the user ID it was issued for."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "type", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if payload["type"] != expected_type:
        raise TokenError("wrong token type")
    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise TokenError("invalid subject") from exc


def hash_token(token: str) -> str:
    """Refresh tokens are stored as SHA-256 hex digests, never in plain text."""
    return hashlib.sha256(token.encode()).hexdigest()
