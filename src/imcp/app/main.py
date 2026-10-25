"""App server. Start with: uvicorn --factory imcp.app.main:create_app"""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from imcp import SERVICE_NAME, SERVICE_VERSION
from imcp.app.answers_api import router as answers_router
from imcp.app.bank_api import router as bank_router
from imcp.app.db import check_db, create_db_engine
from imcp.app.jobs import JobStore
from imcp.app.scope_api import router as scope_router
from imcp.config import AppSettings, describe_config
from imcp.llm import ModelClient

FROM_SETTINGS: Any = object()


def create_app(
    settings: AppSettings | None = None,
    db_check: Callable[[], dict] | None = None,
    session_factory: Callable[[], Session] | None = None,
    model: Any = FROM_SETTINGS,  # a ModelClient (or a stand-in in tests); None = no model
) -> FastAPI:
    settings = settings or AppSettings()
    if db_check is None or session_factory is None:
        engine = create_db_engine(settings.database_url())  # connects lazily, on first use
        if db_check is None:
            db_check = lambda: check_db(engine)  # noqa: E731
        if session_factory is None:
            session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.jobs = JobStore()
    app.state.model = ModelClient.from_settings(settings) if model is FROM_SETTINGS else model
    app.include_router(bank_router)
    app.include_router(scope_router)
    app.include_router(answers_router)

    @app.get("/health")
    def health(check_model: bool = False) -> JSONResponse:
        database = db_check()
        body = {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "status": "ok" if database["ok"] else "degraded",
            "database": database,
            "config": describe_config(settings),
        }
        if check_model:
            m = app.state.model
            body["model"] = m.ping() if m is not None else {"ok": False, "error": "MODEL_BASE_URL or MODEL_NAME not set"}
        return JSONResponse(body, status_code=200 if database["ok"] else 503)

    return app
