import uuid

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import User, UserRole

# Arbitrary constant key for the advisory lock that serialises registrations,
# so exactly one of several concurrent first registrations becomes admin.
_REGISTRATION_LOCK_KEY = 7_346_001


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        """Create a user. The first user ever registered becomes admin.

        Holds a transaction-scoped advisory lock until the caller commits.
        """
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _REGISTRATION_LOCK_KEY}
        )
        is_first = self.session.scalar(select(func.count()).select_from(User)) == 0
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            role=UserRole.ADMIN if is_first else UserRole.USER,
        )
        self.session.add(user)
        self.session.flush()
        return user
