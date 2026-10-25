"""Database tests run against a separate test database (imcp_test), never the app's own data.

Connection: APP_DB_USER / APP_DB_PASSWORD from your .env (or the environment), the Postgres
published on 127.0.0.1:5432 by docker compose, database TEST_DB_NAME (default imcp_test).
If the test database isn't reachable, these tests are skipped.
"""

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


class TestDb(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")
    APP_DB_USER: str = "imcp"
    APP_DB_PASSWORD: SecretStr | None = None
    TEST_DB_HOST: str = "127.0.0.1"
    TEST_DB_PORT: int = 5432
    TEST_DB_NAME: str = "imcp_test"

    def url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.APP_DB_USER,
            password=self.APP_DB_PASSWORD.get_secret_value() if self.APP_DB_PASSWORD else None,
            host=self.TEST_DB_HOST,
            port=self.TEST_DB_PORT,
            database=self.TEST_DB_NAME,
        )


def alembic_config(url: URL) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def db_url() -> URL:
    url = TestDb().url()
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:
        pytest.skip(f"test database not reachable ({type(exc).__name__}); see tests/db/conftest.py")
    return url


@pytest.fixture(scope="session")
def alembic_cfg(db_url) -> Config:
    return alembic_config(db_url)


@pytest.fixture(scope="session")
def engine(db_url):
    """Fresh schema for the test session: migrate down to nothing, then up to the latest version."""
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine):
    """Each test runs in a transaction that is rolled back afterwards."""
    conn = engine.connect()
    trans = conn.begin()
    yield conn
    trans.rollback()
    conn.close()


def session_on(conn) -> Session:
    """A session inside the test's transaction: its commits only release a savepoint."""
    return Session(bind=conn, join_transaction_mode="create_savepoint")


@pytest.fixture
def session(connection):
    s = session_on(connection)
    yield s
    s.close()
