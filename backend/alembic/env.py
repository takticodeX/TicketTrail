import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import app.db.models  # noqa: F401  (registers every model on Base.metadata)
from app.config import DEFAULT_DATABASE_URL
from app.db.base import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests pass the URL explicitly; containers use TT_DATABASE_URL.
    return config.get_main_option("sqlalchemy.url") or os.environ.get(
        "TT_DATABASE_URL", DEFAULT_DATABASE_URL
    )


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
