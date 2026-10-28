"""App server. Start with `uv run imcp-app` (or: uvicorn --factory imcp.app.main:create_app)."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from imcp import SERVICE_NAME, SERVICE_VERSION
from imcp.app.answers_api import router as answers_router
from imcp.app.bank_api import router as bank_router
from imcp.app.db import check_db, create_db_engine
from imcp.app.graph_api import router as graph_router
from imcp.app.jobs import JobStore
from imcp.app.proposal_api import router as proposal_router
from imcp.app.scope_api import router as scope_router
from imcp.config import AppSettings, describe_config, from_env_file
from imcp.llm import EmbeddingClient, ModelClient

FROM_SETTINGS: Any = object()


def create_app(
    settings: AppSettings | None = None,
    db_check: Callable[[], dict] | None = None,
    session_factory: Callable[[], Session] | None = None,
    model: Any = FROM_SETTINGS,  # a ModelClient (or a stand-in in tests); None = no model
    embedder: Any = FROM_SETTINGS,  # an EmbeddingClient (or a stand-in in tests); None = no embeddings
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
    app.state.embedder = EmbeddingClient.from_settings(settings) if embedder is FROM_SETTINGS else embedder
    app.include_router(bank_router)
    app.include_router(scope_router)
    app.include_router(answers_router)
    app.include_router(graph_router)
    app.include_router(proposal_router)

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
            e = app.state.embedder
            body["embeddings"] = e.ping() if e is not None else {"ok": False, "error": "EMBEDDING_MODEL not set"}
        return JSONResponse(body, status_code=200 if database["ok"] else 503)

    return app


def main() -> None:
    """Run the app server without Docker: host and port from APP_HOST and APP_PORT (default 0.0.0.0:8787)."""
    import uvicorn

    settings = from_env_file()
    uvicorn.run(create_app(settings), host=settings.APP_HOST, port=settings.APP_PORT)
