import json

import httpx
import pytest

from imcp.config import AppSettings
from imcp.llm import EmbeddingClient, ModelClient, ModelError, parse_json_object


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


# --- embeddings -------------------------------------------------------------------------------

def embedder_with(handler, key="sk-secret"):
    return EmbeddingClient("https://genai.example/v1", "text-embedding-3-small", key,
                           http=httpx.Client(transport=httpx.MockTransport(handler)))


def embeddings_reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.read())
    # Out of order on purpose: the client must sort by index.
    data = [{"index": i, "embedding": [float(i), 0.5]} for i in range(len(body["input"]))][::-1]
    return httpx.Response(200, json={"data": data, "model": body["model"]})


def test_embedding_url_root_or_full():
    assert EmbeddingClient("https://genai.example/v1/", "m").url == "https://genai.example/v1/embeddings"
    assert EmbeddingClient("https://genai.example/v1/embeddings", "m").url == "https://genai.example/v1/embeddings"


def test_embed_sends_model_input_and_key_and_keeps_order():
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        seen[-1]["auth"] = request.headers.get("authorization")
        return embeddings_reply(request)

    vectors = embedder_with(handler).embed(["a", "b", "c"])
    assert vectors == [[0.0, 0.5], [1.0, 0.5], [2.0, 0.5]]
    assert seen[0]["model"] == "text-embedding-3-small" and seen[0]["input"] == ["a", "b", "c"]
    assert seen[0]["auth"] == "Bearer sk-secret"


def test_embed_batches_large_inputs():
    seen = []

    def handler(request):
        seen.append(len(json.loads(request.read())["input"]))
        return embeddings_reply(request)

    vectors = embedder_with(handler).embed([str(i) for i in range(250)])
    assert seen == [100, 100, 50] and len(vectors) == 250


def test_embed_errors_are_short_and_never_include_the_key():
    def refuse(request):
        raise httpx.ConnectError("certificate verify failed sk-secret")

    with pytest.raises(ModelError) as err:
        embedder_with(refuse).embed(["x"])
    assert "ConnectError" in str(err.value) and "sk-secret" not in str(err.value)
    with pytest.raises(ModelError, match="HTTP 401"):
        embedder_with(lambda r: httpx.Response(401, text="bad key sk-secret")).embed(["x"])
    with pytest.raises(ModelError, match="expected format"):
        embedder_with(lambda r: httpx.Response(200, json={"oops": 1})).embed(["x"])
    with pytest.raises(ModelError, match="wrong number"):
        embedder_with(lambda r: httpx.Response(200, json={"data": []})).embed(["x"])


def test_embedding_ping_reports_dimensions():
    assert embedder_with(embeddings_reply).ping() == {
        "ok": True, "model": "text-embedding-3-small", "dimensions": 2, "latency_ms": pytest.approx(0, abs=1000)}
    assert embedder_with(lambda r: httpx.Response(503)).ping() == {"ok": False, "error": "the embedding model returned HTTP 503"}


def test_embedding_settings_fall_back_to_the_chat_models():
    base = dict(DB_USER="u", DB_PASSWORD="p", DB_NAME="d", MODEL_BASE_URL="https://genai.example/v1",
                MODEL_NAME="chat", MODEL_API_KEY="chat-key")
    assert EmbeddingClient.from_settings(AppSettings(**base)) is None  # no EMBEDDING_MODEL
    same = EmbeddingClient.from_settings(AppSettings(**base, EMBEDDING_MODEL="text-embedding-3-small"))
    assert same.url == "https://genai.example/v1/embeddings" and same._api_key == "chat-key"
    other = EmbeddingClient.from_settings(AppSettings(
        **base, EMBEDDING_MODEL="e", EMBEDDING_BASE_URL="https://embed.example/v2", EMBEDDING_API_KEY="embed-key"))
    assert other.url == "https://embed.example/v2/embeddings" and other._api_key == "embed-key"
    no_chat = AppSettings(DB_USER="u", DB_PASSWORD="p", DB_NAME="d", EMBEDDING_MODEL="e")
    assert EmbeddingClient.from_settings(no_chat) is None


def test_a_request_can_have_its_own_timeout():
    seen = {}

    def handler(request: httpx.Request):
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    client_with(handler).chat([], timeout=240)
    assert seen["timeout"]["read"] == 240
