import json
import os

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imcp.config import McpSettings
from imcp.mcp_server import build_server, pick_csv
from tests.test_health import _tool_text


def stub_app(received: list, status: int = 200):
    app = FastAPI()

    @app.post("/bank/loads")
    async def loads(request: Request):
        body = await request.json()
        received.append(body)
        return JSONResponse({"applied": body["apply"], "counts": {"new": 1}}, status_code=status)

    return app


def server_for(tmp_path, received, status=200):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app(received, status)), base_url="http://app.test")
    return build_server(McpSettings(IMCP_DATA_DIR=tmp_path), client=client)


@pytest.mark.anyio
async def test_sends_the_newest_csv_as_a_dry_run(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "bank.csv"
    old.write_text("id\nold\n")
    new.write_text("﻿id\nnew\n")  # Google adds no BOM, but Excel does
    os.utime(old, (1, 1))
    received = []
    text = _tool_text(await server_for(tmp_path, received).call_tool("im_bank_load", {}))
    assert received[0]["csv"] == "id\nnew\n" and received[0]["apply"] is False
    assert received[0]["source_ref"].startswith("bank.csv (modified ")
    assert json.loads(text)["file"] == "bank.csv"


@pytest.mark.anyio
async def test_named_file_and_apply(tmp_path):
    (tmp_path / "a.csv").write_text("id\n")
    received = []
    await server_for(tmp_path, received).call_tool("im_bank_load", {"file": "a.csv", "apply": True})
    assert received[0]["apply"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["../secret.csv", "notes.txt", "/etc/passwd"])
async def test_only_csv_files_inside_the_data_folder(tmp_path, name):
    (tmp_path.parent / "secret.csv").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    received = []
    text = _tool_text(await server_for(tmp_path, received).call_tool("im_bank_load", {"file": name}))
    assert "Only .csv files inside" in text and received == []


@pytest.mark.anyio
async def test_explains_how_to_get_the_csv(tmp_path):
    received = []
    text = _tool_text(await server_for(tmp_path / "missing", received).call_tool("im_bank_load", {}))
    assert "Download the bank's Project Scope tab as CSV" in text and received == []


@pytest.mark.anyio
async def test_relays_app_errors(tmp_path):
    (tmp_path / "a.csv").write_text("id\n")
    text = _tool_text(await server_for(tmp_path, [], status=500).call_tool("im_bank_load", {}))
    assert "HTTP 500" in text


def test_pick_csv_rejects_missing_named_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_csv(tmp_path, "nope.csv")
