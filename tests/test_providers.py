import argparse
import io
import json
import urllib.request
from pathlib import Path

import pytest

from agentforge.cli import model_backend
from agentforge.core import ForgeError, read_json, redact, write_json
from agentforge.providers import (
    BUNDLE_SCHEMA,
    ModelConfig,
    ModelGenerator,
    NoRedirect,
    OpenAITransport,
    RecordedTransport,
    ResponsesBackend,
)

FIXTURES = Path(__file__).resolve().parents[1] / "examples/v02"


def valid_response():
    return read_json(FIXTURES / "integer-stats.response.json")["responses"][0]


def test_responses_schema_and_usage_receipt(tmp_path):
    transport = RecordedTransport([valid_response()])
    backend = ResponsesBackend(ModelConfig(model="explicit-test-model"), transport)
    output = backend.request({"goal": "compute"}, BUNDLE_SCHEMA)
    assert output["files"]
    request = transport.requests[0]
    assert request["model"] == "explicit-test-model"
    assert request["store"] is False and not request.get("tools")
    assert request["text"]["format"]["strict"]
    backend.save_receipts(tmp_path / "receipts.json")
    receipt = read_json(tmp_path / "receipts.json")["calls"][0]
    assert receipt["offline_fixture"] and receipt["usage"]["input_tokens"] == 100
    assert receipt["cost_usd"] == "0"
    assert redact({"token_count": 20, "access_token": "fake"}) == {
        "token_count": 20,
        "access_token": "[REDACTED]",
    }


@pytest.mark.parametrize(
    "mutation", ["incomplete", "refusal", "bad-json", "missing-usage", "bad-shape", "excess-usage"]
)
def test_provider_failure_modes_keep_reservation(mutation):
    value = valid_response()
    if mutation == "incomplete":
        value["status"] = "incomplete"
    elif mutation == "refusal":
        value["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
    elif mutation == "bad-json":
        value["output"][0]["content"][0]["text"] = "{"
    elif mutation == "missing-usage":
        value.pop("usage")
    elif mutation == "excess-usage":
        value["usage"]["output_tokens"] = 999999
    else:
        value["output"][0]["content"][0]["text"] = "{}"
    transport = RecordedTransport([value])
    backend = ResponsesBackend(ModelConfig(model="offline", max_requests=1), transport)
    with pytest.raises((ForgeError, ValueError)):
        backend.request({}, BUNDLE_SCHEMA)
    assert backend.receipts[0]["status"].startswith("failed-or-unknown")
    assert backend.reserved_tokens > 0
    with pytest.raises(ForgeError, match="request budget"):
        backend.request({}, BUNDLE_SCHEMA)
    assert len(transport.requests) == 1


def test_live_transport_payload_without_any_network(monkeypatch, tmp_path):
    observed = []

    class Opener:
        def open(self, request, timeout):
            observed.append(request)
            assert request.full_url == "https://api.openai.com/v1/responses"
            assert request.get_header("Authorization") == "Bearer fake-test-value"
            return io.BytesIO(json.dumps(valid_response()).encode())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    transport = OpenAITransport("fake-test-value", approved=True)
    from agentforge.billing import BudgetLedger

    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("test", dollars=1, tokens=100000, requests=10)
    backend = ResponsesBackend(
        ModelConfig(
            model="explicit-model",
            max_cost_usd=1,
            input_usd_per_million=1,
            output_usd_per_million=2,
        ),
        transport,
        ledger=ledger,
        account="test",
    )
    backend.request({}, BUNDLE_SCHEMA)
    assert len(observed) == 1 and backend.receipts[0]["cost_usd"] == "0.0005"
    assert "fake-test-value" not in json.dumps(backend.receipts)


def test_spend_cap_blocks_before_transport():
    class Denied:
        offline = False

        def post(self, *args, **kwargs):
            raise AssertionError("No paid request may be sent")

    backend = ResponsesBackend(
        ModelConfig(
            model="explicit",
            max_cost_usd=0.000000001,
            input_usd_per_million=1,
            output_usd_per_million=1,
        ),
        Denied(),
    )
    with pytest.raises(ForgeError, match="spend cap"):
        backend.request({}, BUNDLE_SCHEMA)
    assert not backend.receipts


def test_unknown_outcome_has_no_automatic_retry(tmp_path):
    class Failure:
        offline = False
        calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            raise ForgeError("unknown outcome")

    transport = Failure()
    from agentforge.billing import BudgetLedger

    ledger = BudgetLedger(tmp_path / "budget")
    ledger.create("test", dollars=1, tokens=100000, requests=10)
    backend = ResponsesBackend(
        ModelConfig(
            model="explicit", max_cost_usd=1, input_usd_per_million=1, output_usd_per_million=1
        ),
        transport,
        ledger=ledger,
        account="test",
    )
    with pytest.raises(ForgeError):
        backend.request({}, BUNDLE_SCHEMA)
    assert transport.calls == 1 and backend.reserved_cost > 0


def test_live_approval_gate_and_redirect_denial():
    with pytest.raises(ForgeError, match="approval"):
        OpenAITransport("fake-test-value")
    with pytest.raises(ForgeError, match="redirect"):
        NoRedirect().redirect_request(None)


def test_no_credential_read_before_live_approval(tmp_path, monkeypatch):
    write_json(
        tmp_path / "config.json",
        {
            "model": "explicit",
            "max_cost_usd": 1,
            "input_usd_per_million": 1,
            "output_usd_per_million": 1,
        },
    )
    import os

    class NoEnvironment(dict):
        def get(self, *args, **kwargs):
            raise AssertionError("Credential discovery is forbidden")

    monkeypatch.setattr(os, "environ", NoEnvironment())
    args = argparse.Namespace(
        model_receipts=tmp_path / "receipts.json",
        model_config=tmp_path / "config.json",
        response=None,
        approve_model_request=False,
        credential_env="OPENAI_API_KEY",
    )
    with pytest.raises(ForgeError, match="approval"):
        model_backend(args)


def test_persistent_account_is_checked_before_selected_key_read(tmp_path, monkeypatch):
    import os

    write_json(
        tmp_path / "config.json",
        {
            "model": "explicit",
            "max_cost_usd": 1,
            "input_usd_per_million": 1,
            "output_usd_per_million": 1,
        },
    )

    class NoEnvironment(dict):
        def get(self, *args, **kwargs):
            raise AssertionError("No key read before the durable account gate")

    monkeypatch.setattr(os, "environ", NoEnvironment())
    args = argparse.Namespace(
        model_receipts=tmp_path / "receipts.json",
        model_config=tmp_path / "config.json",
        response=None,
        approve_model_request=True,
        credential_env="OPENAI_API_KEY",
        home=tmp_path,
        budget_account=None,
    )
    with pytest.raises(ForgeError, match="budget-account"):
        model_backend(args)


def test_model_planning_seals_identity():
    value = read_json(FIXTURES / "integer-stats.planning-response.json")["responses"][0]
    transport = RecordedTransport([value])
    backend = ResponsesBackend(ModelConfig(model="offline"), transport)
    spec = read_json(FIXTURES / "integer-stats.plan.json")
    result = backend.plan(spec["goal"], spec["name"], spec["kind"])
    assert result == spec
    request = transport.requests[0]
    assert json.loads(request["input"])["operation"] == "plan"
    assert "not program source" in request["instructions"]
    assert "json.load(sys.stdin)" not in request["instructions"]


def test_local_planning_uses_typed_schemas_and_preserves_explicit_contract(tmp_path):
    fields = {
        "inputs": {"type": "string", "maxLength": 512},
        "outputs": {"type": "integer"},
        "steps": ["Count ASCII digits"],
        "risks": ["Untrusted generated code"],
        "acceptance": ["Ignore non-ASCII digits"],
        "test_plan": ["Independent cases"],
    }
    response = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(fields)}]}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }
    transport = RecordedTransport([response])
    transport.kind = "local-llama.cpp"
    backend = ResponsesBackend(ModelConfig(model="typed-plan-fixture"), transport)
    contract = {"inputs": fields["inputs"]}
    spec = backend.plan("Count ASCII digits", "digit-count", "python-json", contract=contract)
    assert spec["inputs"] == contract["inputs"] and spec["name"] == "digit-count"
    request = transport.requests[0]
    assert json.loads(request["input"])["planning_format"] == "typed-plan"
    assert json.loads(request["input"])["template"]["inputs"] == contract["inputs"]
    assert "outputs" not in json.loads(request["input"])["template"]
    assert "spec_json" not in request["text"]["format"]["schema"]["properties"]
    backend.save_receipts(tmp_path / "audit.json")
    assert read_json(tmp_path / "audit.json")["planning_response"] == fields


def test_planning_cannot_overwrite_an_operator_contract():
    value = read_json(FIXTURES / "integer-stats.planning-response.json")["responses"][0]
    backend = ResponsesBackend(ModelConfig(model="fixture"), RecordedTransport([value]))
    spec = read_json(FIXTURES / "integer-stats.plan.json")
    with pytest.raises(ForgeError, match="sealed input/output contract"):
        backend.plan(
            spec["goal"], spec["name"], spec["kind"], contract={"inputs": {"type": "string"}}
        )


def test_local_plan_self_review_is_bounded_and_auditable():
    first = {
        "inputs": {"type": "object"},
        "outputs": {"type": "integer"},
        "steps": ["Count digits"],
        "risks": ["Untrusted source"],
        "acceptance": ["Ignore other characters"],
        "test_plan": ["Independent tests"],
    }
    corrected = {**first, "inputs": {"type": "string"}}
    responses = [
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(fields)}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        }
        for fields in [first, corrected]
    ]
    transport = RecordedTransport(responses)
    transport.kind = "local-llama.cpp"
    backend = ResponsesBackend(
        ModelConfig(model="review-fixture", total_token_limit=100000), transport
    )
    result = backend.plan(
        "The JSON root is a string; count digits", "digits", "python-json", review=True
    )
    assert result["inputs"] == {"type": "string"}
    assert not {"inputs", "outputs"} & json.loads(transport.requests[0]["input"])["template"].keys()
    assert json.loads(transport.requests[1]["input"])["review_candidate"] == first
    assert backend.planning_attempts == [first, corrected] and len(backend.receipts) == 2


def test_plan_review_refuses_insufficient_request_budget_before_transport():
    transport = RecordedTransport([])
    transport.kind = "local-llama.cpp"
    backend = ResponsesBackend(ModelConfig(model="review-fixture", max_requests=1), transport)
    with pytest.raises(ForgeError, match="two remaining"):
        backend.plan("Count", "count", "python-json", review=True)
    assert not transport.requests


def test_generation_is_extensible_beyond_known_offline_templates(tmp_path):
    # The adapter receives code from the transport, not a builtin operation selector.
    response = read_json(FIXTURES / "rot13.response.json")["responses"][0]
    backend = ResponsesBackend(ModelConfig(model="offline"), RecordedTransport([response]))
    spec = read_json(FIXTURES / "rot13.plan.json")
    root = ModelGenerator(backend).generate(spec, tmp_path / "rot13")
    assert (root / "scripts/main.wasm").is_file()


def test_existing_destination_is_rejected_before_model_request(tmp_path):
    transport = RecordedTransport([valid_response()])
    backend = ResponsesBackend(ModelConfig(model="offline"), transport)
    target = tmp_path / "integer-stats"
    target.mkdir()
    with pytest.raises(ForgeError, match="new directory"):
        ModelGenerator(backend).generate(read_json(FIXTURES / "integer-stats.plan.json"), target)
    assert not transport.requests and not backend.receipts
