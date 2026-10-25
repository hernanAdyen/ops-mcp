"""Our internal model, called as an OpenAI-compatible chat completions API.

Configured only by environment variables (MODEL_BASE_URL, MODEL_NAME, MODEL_API_KEY).
MODEL_BASE_URL may be the API root (…/v1) or the full …/v1/chat/completions URL.
TLS uses the system certificate store, so the container's internal CA is trusted.
Errors never include the key, and the IM's text isn't logged.
"""

import json
import logging
import ssl
import time

import httpx

from imcp.config import AppSettings

log = logging.getLogger("imcp.llm")


class ModelError(RuntimeError):
    """A short, safe description of what went wrong."""


class ModelClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, *,
                 http: httpx.Client | None = None, timeout: float = 90):
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/chat/completions") else f"{url}/chat/completions"
        self.model = model
        self._api_key = api_key
        self._http = http or httpx.Client(verify=ssl.create_default_context(), timeout=timeout)

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "ModelClient | None":
        if not (settings.MODEL_BASE_URL and settings.MODEL_NAME):
            return None
        return cls(str(settings.MODEL_BASE_URL), settings.MODEL_NAME, settings.MODEL_API_KEY)

    def chat(self, messages: list[dict], *, max_tokens: int = 1500, temperature: float = 0.0,
             timeout: float | None = None) -> str:
        """timeout: seconds for this request, when it may take longer than the client's default."""
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        extra = {"timeout": timeout} if timeout else {}
        try:
            res = self._http.post(self.url, json=body, headers=headers, **extra)
        except httpx.HTTPError as exc:
            log.warning("model request failed: %s", type(exc).__name__)
            raise ModelError(f"could not reach the model ({type(exc).__name__})") from exc
        if res.status_code != 200:
            log.warning("model returned HTTP %s: %s", res.status_code, res.text[:300])
            raise ModelError(f"the model returned HTTP {res.status_code}")
        try:
            return res.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("the model's reply wasn't in the expected format") from exc

    def ping(self) -> dict:
        """A tiny request, to check the configuration (URL, key, certificates, network)."""
        started = time.monotonic()
        try:
            self.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=5)
        except ModelError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "model": self.model, "latency_ms": int((time.monotonic() - started) * 1000)}


def parse_json_object(text: str) -> dict:
    """The JSON object in a model reply, ignoring code fences or text around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ModelError("the model didn't return JSON")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ModelError("the model returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ModelError("the model didn't return a JSON object")
    return value
