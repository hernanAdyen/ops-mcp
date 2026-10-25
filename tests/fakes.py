"""Stand-ins for our model, so tests never call the real endpoint."""

import json


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
