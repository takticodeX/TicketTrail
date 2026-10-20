"""Declarative base shared by all models."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Stable constraint names, so Alembic migrations stay predictable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class TimestampedModel(Base):
    """UUID primary key plus created_at / updated_at, as every table needs."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OwnedModel(TimestampedModel):
    """A named row that belongs to one user or to one organization, never both.

    Repositories filter every query on its owner. Names are unique per owner.
    """

    __abstract__ = True

    name: Mapped[str] = mapped_column(String(100))

    @declared_attr
    def owner_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805  (SQLAlchemy declared_attr)
        return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        # RESTRICT: an organization is deleted only once it owns nothing.
        return mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)


def ownership_constraints(table: str) -> tuple[CheckConstraint, UniqueConstraint, UniqueConstraint]:
    """Exactly one owner, and unique names per user and per organization."""
    return (
        CheckConstraint("(owner_id IS NULL) <> (organization_id IS NULL)", name="one_owner"),
        UniqueConstraint("owner_id", "name", name=f"uq_{table}_owner_name"),
        UniqueConstraint("organization_id", "name", name=f"uq_{table}_organization_name"),
    )
