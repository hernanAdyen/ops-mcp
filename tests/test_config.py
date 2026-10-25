import json

import pytest
from pydantic import ValidationError

from imcp.config import AppSettings, McpSettings, describe_config


DB = dict(DB_USER="imcp", DB_PASSWORD="pw", DB_NAME="imcp")


def test_requires_database_settings(monkeypatch):
    for k in ("DATABASE_URL", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        AppSettings()


def test_password_with_special_characters_is_safe():
    s = AppSettings(DB_USER="imcp", DB_PASSWORD="p@ss:w/rd#?%", DB_NAME="imcp")
    url = s.database_url()
    assert url.host == "postgres"
    assert url.password == "p@ss:w/rd#?%"
    assert url.drivername == "postgresql+psycopg"


def test_defaults():
    s = AppSettings(**DB)
    assert s.APP_PORT == 8787
    assert s.FLAG_RECOMMENDER == "curated"
    assert s.FLAG_SANITIZE is True
    assert s.FLAG_CANDIDATE_QUEUE is False


def test_database_url_override_gets_psycopg_driver():
    s = AppSettings(DATABASE_URL="postgres://u:p@h:5432/d")
    assert s.database_url().drivername == "postgresql+psycopg"
    assert s.database_url().host == "h"


def test_empty_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("DB_USER", "imcp"); monkeypatch.setenv("DB_PASSWORD", "pw"); monkeypatch.setenv("DB_NAME", "imcp")
    monkeypatch.setenv("MODEL_BASE_URL", "")
    assert AppSettings().MODEL_BASE_URL is None


def test_invalid_link_is_rejected():
    with pytest.raises(ValidationError):
        AppSettings(**DB, QUESTION_BANK_URL="not a url")


def test_invalid_flag_is_rejected():
    with pytest.raises(ValidationError):
        AppSettings(**DB, FLAG_RECOMMENDER="magic")


def test_describe_config_never_reveals_values():
    s = AppSettings(
        DB_USER="imcp", DB_PASSWORD="dbsecret", DB_NAME="imcp",
        MODEL_API_KEY="super-secret-key",
        MODEL_BASE_URL="https://model.example.com/v1",
    )
    described = json.dumps(describe_config(s))
    for secret in ("super-secret-key", "model.example.com", "dbsecret"):
        assert secret not in described
    assert describe_config(s)["model"]["apiKey"] is True


def test_mcp_default_app_url():
    assert str(McpSettings().APP_SERVER_URL).startswith("http://localhost:8787")
