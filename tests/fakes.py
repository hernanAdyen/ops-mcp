"""Stand-ins for our model, so tests never call the real endpoint."""

import hashlib
import json
import re


class FakeModel:
    """Returns a fixed reply and remembers what it was asked."""

    model = "fake-model"

    def __init__(self, reply: dict | str | Exception):
        self.reply = reply
        self.calls: list[list[dict]] = []

    def chat(self, messages, *, max_tokens=1500, temperature=0.0, timeout=None) -> str:
        self.calls.append(messages)
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)

    def ping(self) -> dict:
        return {"ok": True, "model": self.model, "latency_ms": 1}


class FakeEmbedder:
    """Deterministic vectors from the words in a text: texts that share words are close."""

    model = "fake-embedding"
    dim = 256

    def __init__(self, fail: Exception | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail is not None:
            raise self.fail
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        return v

    def ping(self) -> dict:
        return {"ok": True, "model": self.model, "dimensions": self.dim, "latency_ms": 1}
