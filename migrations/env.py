"""Alembic environment: the database URL comes from our settings (DB_* variables or DATABASE_URL)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from imcp.config import from_env_file
from imcp.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url():
    # Tests (and other tools) can pass a URL directly; otherwise use the app's settings.
    return config.attributes.get("url") or from_env_file().database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
