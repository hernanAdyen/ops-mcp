import httpx
import pytest

from imcp.config import AppSettings
from imcp.llm import ModelClient, ModelError, parse_json_object


def client_with(handler, base_url="https://genai.example/v1", key="sk-secret"):
    return ModelClient(base_url, "test-model", key, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_root_or_full_url_both_work():
    assert ModelClient("https://genai.example/v1/", "m").url == "https://genai.example/v1/chat/completions"
    assert ModelClient("https://genai.example/v1/chat/completions", "m").url == "https://genai.example/v1/chat/completions"


def test_sends_model_messages_and_key():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    assert client_with(handler).chat([{"role": "user", "content": "hi"}]) == "OK"
    assert seen["auth"] == "Bearer sk-secret" and '"model":"test-model"' in seen["body"].replace(" ", "")


def test_errors_are_short_and_never_include_the_key():
    def refuse(request):
        raise httpx.ConnectError("certificate verify failed")

    with pytest.raises(ModelError) as err:
        client_with(refuse).chat([])
    assert "ConnectError" in str(err.value) and "sk-secret" not in str(err.value)

    with pytest.raises(ModelError, match="HTTP 401"):
        client_with(lambda r: httpx.Response(401, text="bad key sk-secret")).chat([])
    with pytest.raises(ModelError, match="expected format"):
        client_with(lambda r: httpx.Response(200, json={"oops": 1})).chat([])


def test_ping_reports_ok_or_the_problem():
    ok = client_with(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})).ping()
    assert ok["ok"] is True and ok["model"] == "test-model"
    bad = client_with(lambda r: httpx.Response(503)).ping()
    assert bad == {"ok": False, "error": "the model returned HTTP 503"}


def test_from_settings_needs_url_and_name():
    base = dict(DB_USER="u", DB_PASSWORD="p", DB_NAME="d")
    assert ModelClient.from_settings(AppSettings(**base)) is None
    client = ModelClient.from_settings(AppSettings(**base, MODEL_BASE_URL="https://genai.example/v1", MODEL_NAME="test-model"))
    assert client.model == "test-model"


def test_parse_json_object():
    assert parse_json_object('text {"a": 1} more') == {"a": 1}
    with pytest.raises(ModelError):
        parse_json_object("[1, 2]")
    with pytest.raises(ModelError):
        parse_json_object("{not json}")


def test_a_request_can_have_its_own_timeout():
    seen = {}

    def handler(request: httpx.Request):
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    client_with(handler).chat([], timeout=240)
    assert seen["timeout"]["read"] == 240
