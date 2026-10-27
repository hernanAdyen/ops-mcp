import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imcp.config import McpSettings
from imcp.mcp_server import build_server
from tests.test_health import _tool_text

RULES = "prefix,include,max_depth,channels,pillars,categories,platforms,note\n/,no,,,,,,\n/plugins,yes,,,,,,\n"


def stub_app(received: list, pending: bool = False, status: int = 200):
    app = FastAPI()

    @app.post("/graph/loads/docs")
    async def loads(request: Request):
        body = await request.json()
        received.append({"body": body, "wait": request.query_params.get("wait")})
        if pending:
            return JSONResponse({"job_id": "11111111-1111-1111-1111-111111111111", "pending": True})
        return JSONResponse({"job_id": "j", "pending": False, "applied": body["apply"], "counts": {"new": 2}}, status_code=status)

    @app.get("/graph/jobs/{job_id}")
    async def job(job_id: str):
        received.append({"job": job_id})
        return JSONResponse({"job_id": job_id, "pending": False, "applied": False, "counts": {"new": 2}})

    return app


def server_for(tmp_path, received, **kw):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app(received, **kw)), base_url="http://app.test")
    return build_server(McpSettings(IMCP_DATA_DIR=tmp_path), client=client)


def rules_file(tmp_path, name="adyen-doc-pages.csv"):
    (tmp_path / "graph").mkdir(exist_ok=True)
    (tmp_path / "graph" / name).write_text(RULES)


@pytest.mark.anyio
async def test_sends_the_default_rules_file_as_a_dry_run(tmp_path):
    rules_file(tmp_path)
    received = []
    text = _tool_text(await server_for(tmp_path, received).call_tool("im_graph_load_docs", {}))
    sent = received[0]
    assert sent["body"]["rules_csv"] == RULES and sent["body"]["apply"] is False and sent["wait"] == "40"
    assert sent["body"]["source_ref"].startswith("adyen-doc-pages.csv (modified ")
    assert json.loads(text)["counts"] == {"new": 2}


@pytest.mark.anyio
async def test_named_file_and_apply(tmp_path):
    rules_file(tmp_path, "trimmed.csv")
    received = []
    await server_for(tmp_path, received).call_tool("im_graph_load_docs", {"file": "trimmed.csv", "apply": True})
    assert received[0]["body"]["apply"] is True and received[0]["body"]["source_ref"].startswith("trimmed.csv")


@pytest.mark.anyio
async def test_explains_a_missing_rules_file(tmp_path):
    received = []
    text = _tool_text(await server_for(tmp_path, received).call_tool("im_graph_load_docs", {}))
    assert "There's no file named adyen-doc-pages.csv" in text and received == []


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["../question-bank.csv", "notes.txt"])
async def test_only_csv_files_inside_the_graph_folder(tmp_path, name):
    rules_file(tmp_path)
    (tmp_path / "question-bank.csv").write_text("x")
    received = []
    text = _tool_text(await server_for(tmp_path, received).call_tool("im_graph_load_docs", {"file": name}))
    assert "Only .csv files inside" in text and received == []


@pytest.mark.anyio
async def test_pending_points_at_im_graph_wait(tmp_path):
    rules_file(tmp_path)
    received = []
    server = server_for(tmp_path, received, pending=True)
    data = json.loads(_tool_text(await server.call_tool("im_graph_load_docs", {})))
    assert data["pending"] is True and "im_graph_wait" in data["next"]
    text = _tool_text(await server.call_tool("im_graph_wait", {"job_id": data["job_id"]}))
    assert received[-1] == {"job": data["job_id"]} and json.loads(text)["counts"] == {"new": 2}
    assert "job_id should be" in _tool_text(await server.call_tool("im_graph_wait", {"job_id": "nope"}))
