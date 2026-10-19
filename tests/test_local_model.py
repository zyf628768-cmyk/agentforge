import io
import json
import urllib.request

import pytest

from agentforge.billing import BudgetLedger
from agentforge.core import ForgeError
from agentforge.local_model import LocalTransport
from agentforge.providers import BUNDLE_SCHEMA, ModelConfig, ResponsesBackend


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.openai.com/v1/chat/completions",
        "http://localhost:8080/v1/chat/completions",
        "http://127.0.0.1:8080/v1/chat/completions?redirect=remote",
        "http://user:pass@127.0.0.1:8080/v1/chat/completions",
        "http://127.0.0.1/v1/chat/completions",
        "http://192.168.1.1:8080/v1/chat/completions",
    ],
)
def test_local_transport_refuses_remote_or_ambiguous_endpoints(endpoint):
    with pytest.raises(ForgeError):
        LocalTransport(endpoint, approved=True)


def test_actual_local_inference_is_distinct_from_fixture_and_has_durable_usage(
    tmp_path, monkeypatch
):
    observed = []

    class Opener:
        def open(self, request, timeout):
            assert not request.has_header("Authorization")
            observed.append(json.loads(request.data))
            return io.BytesIO(
                json.dumps(
                    {
                        "id": "local-test",
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": '{"files":[]}'}}
                        ],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                    }
                ).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("local", dollars=0, tokens=100000, requests=2)
    backend = ResponsesBackend(
        ModelConfig(model="local"),
        LocalTransport("http://127.0.0.1:31871/v1/chat/completions", approved=True),
        ledger=ledger,
        account="local",
    )
    # This intentionally violates the engineering schema; even failure must retain reservation.
    with pytest.raises(ForgeError, match="schema"):
        backend.request({}, BUNDLE_SCHEMA)
    assert not backend.receipts[0]["offline_fixture"]
    assert backend.receipts[0]["cost_usd"] == "0"
    assert ledger.status("local")["unresolved"][0]["state"] == "unknown"
    assert observed[0]["response_format"]["json_schema"]["strict"]
