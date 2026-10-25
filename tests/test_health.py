import json

import httpx
import pytest
from fastapi.testclient import TestClient

from imcp.app.main import create_app
from imcp.config import AppSettings
from imcp.mcp_server import build_server

SETTINGS = AppSettings(DB_USER="imcp", DB_PASSWORD="pw", DB_NAME="imcp", MODEL_API_KEY="secret")
DB_OK = lambda: {"ok": True, "version": "PostgreSQL 18.0"}  # noqa: E731
DB_DOWN = lambda: {"ok": False, "error": "connection refused"}  # noqa: E731


def test_health_ok():
    res = TestClient(create_app(SETTINGS, db_check=DB_OK)).get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert "secret" not in res.text


def test_health_degraded_when_db_down():
    res = TestClient(create_app(SETTINGS, db_check=DB_DOWN)).get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"


def _tool_text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    first = content[0] if isinstance(content, list) else content.content[0]
    return first.text


@pytest.mark.anyio
async def test_mcp_im_health_relays_app_health():
    app = create_app(SETTINGS, db_check=DB_OK)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test")
    server = build_server(client=client)
    tools = await server.list_tools()
    assert "im_health" in [t.name for t in tools]
    text = _tool_text(await server.call_tool("im_health", {}))
    assert json.loads(text)["status"] == "ok"


@pytest.mark.anyio
async def test_mcp_im_health_explains_when_app_down():
    def refuse(request):
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    server = build_server(client=client)
    text = _tool_text(await server.call_tool("im_health", {}))
    assert "docker compose up" in text


def test_db_error_does_not_leak_connection_details():
    from sqlalchemy import create_engine

    from imcp.app.db import check_db

    engine = create_engine("postgresql+psycopg://imcp:topsecret@127.0.0.1:1/imcp")
    result = check_db(engine)
    assert result["ok"] is False
    assert "topsecret" not in result["error"] and "127.0.0.1" not in result["error"]
