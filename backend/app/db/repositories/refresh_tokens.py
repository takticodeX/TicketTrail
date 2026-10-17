import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> RefreshToken:
        token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(token)
        self.session.flush()
        return token

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """Load and row-lock a token, so two parallel refreshes can't both rotate it."""
        return self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    def revoke_by_hash(self, token_hash: str) -> None:
        self.session.execute(
            update(RefreshToken).where(RefreshToken.token_hash == token_hash).values(revoked=True)
        )

    def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
