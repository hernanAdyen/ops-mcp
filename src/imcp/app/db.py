import logging
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

log = logging.getLogger("imcp.db")


def create_db_engine(url: URL) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=5)


def check_db(engine: Engine) -> dict:
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
        return {"ok": True, "version": version}
    except Exception as exc:
        # Full details (which can include hosts and users) go to the server log only.
        log.warning("database check failed: %s", exc)
        return {"ok": False, "error": f"cannot connect to the database ({type(exc).__name__}); see app logs"}


def get_session(request: Request) -> Iterator[Session]:
    """One database session per request. Endpoints commit explicitly; anything else is rolled back."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
