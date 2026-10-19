"""Explicit local llama.cpp transport. Literal loopback only, no key or proxy reads."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .core import ForgeError, strict_json
from .providers import NoRedirect


class LocalTransport:
    offline = False  # Actual inference must never be labelled a recorded fixture.
    free = True
    kind = "local-llama.cpp"

    def __init__(self, endpoint: str, *, approved: bool = False):
        parsed = urllib.parse.urlsplit(endpoint)
        if not approved:
            raise ForgeError("Local inference requires explicit --approve-local-model")
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/v1/chat/completions"
            or not parsed.port
        ):
            raise ForgeError(
                "Local model endpoint must be literal loopback HTTP with explicit port and /v1/chat/completions"
            )
        self.endpoint = endpoint

    def post(self, payload: dict, *, timeout: float) -> dict:
        context = strict_json(payload.get("input", "{}"))
        planning = isinstance(context, dict) and context.get("operation") == "plan"
        source_hint = (
            "" if planning else "Write actual source code in source, not a path or filename.\n"
        )
        body = {
            "model": payload["model"],
            "messages": [
                {
                    "role": "system",
                    "content": payload["instructions"]
                    + "\nYour reply must be one JSON object conforming to this schema. "
                    + source_hint
                    + json.dumps(payload["text"]["format"]["schema"]),
                },
                {"role": "user", "content": payload["input"]},
            ],
            "max_tokens": payload["max_output_tokens"],
            "temperature": 0,
            "seed": 17,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": payload["text"]["format"]["name"],
                    "strict": True,
                    "schema": payload["text"]["format"]["schema"],
                },
            },
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ForgeError("Local model response exceeds byte limit")
            value = strict_json(raw)
            if not isinstance(value, dict):
                raise ForgeError("Local model envelope must be an object")
            choices = value.get("choices")
            usage = value.get("usage")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
                or choices[0].get("finish_reason") != "stop"
                or not isinstance(choices[0].get("message"), dict)
                or not isinstance(choices[0].get("message", {}).get("content"), str)
                or not isinstance(usage, dict)
            ):
                raise ForgeError("Local model output incomplete or malformed")
            return {
                "id": value.get("id"),
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": choices[0]["message"]["content"]}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                },
            }
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            raise ForgeError(
                "Local inference failed or outcome unknown; reservation retained"
            ) from None
