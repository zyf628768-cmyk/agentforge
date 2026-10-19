import io
import json
import urllib.request

import pytest

from agentforge.billing import BudgetLedger
from agentforge.core import ForgeError
from agentforge.local_model import LocalTransport
from agentforge.providers import (
    BUNDLE_SCHEMA,
    ModelConfig,
    ModelGenerator,
    RecordedTransport,
    ResponsesBackend,
)
from agentforge.spec import general_plan


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


def test_repair_separates_generated_oracle_and_excludes_independent_feedback(tmp_path):
    artifact = {
        "diagnosis": "generated-expectation",
        "contract_summary": "The root is an integer. Return it unchanged.",
        "source": "import json,sys\njson.dump(json.load(sys.stdin),sys.stdout)\n",
        "readme": "Echo a JSON integer.",
        "tests": [{"id": "self-check", "input": 7, "expected": 7}],
        "example_input": 7,
        "example_output": 7,
    }
    response = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(artifact)}]}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }
    transport = RecordedTransport([response, response, response])
    transport.kind = "local-llama.cpp"
    generator = ModelGenerator(
        ResponsesBackend(ModelConfig(model="test-fixture", max_requests=3), transport),
        example_inputs=[7],
    )
    generator.feedback = [
        {
            "id": "self-check",
            "suite": "unit",
            "passed": False,
            "input": 7,
            "expected": 8,
            "actual": {"ok": True, "output": 7},
        },
        {
            "id": "private",
            "suite": "independent",
            "passed": False,
            "input": "PRIVATE-EVALUATOR-SENTINEL",
            "expected": 0,
        },
    ]
    spec = general_plan(
        "Echo the input integer",
        "echo-integer",
        "python-json",
        inputs={"type": "integer"},
        outputs={"type": "integer"},
    )
    path = generator.generate(spec, tmp_path / "echo-integer")
    request = transport.requests[0]
    payload = json.loads(request["input"])
    assert payload["operation"] == "repair"
    assert payload["operator_example_inputs"] == [7]
    assert "PRIVATE-EVALUATOR-SENTINEL" not in request["input"]
    assert payload["generated_test_failures"][0]["generated_expected"] == 8
    assert payload["generated_test_failures"][0]["observation"]["output"] == 7
    assert generator.last_diagnosis == "generated-expectation"
    assert json.loads((path / "tests/cases.json").read_text())[0]["expected"] == 7
    generator.generate(spec, tmp_path / "retry" / "echo-integer")
    retry = json.loads(transport.requests[1]["input"])
    assert retry["previous_model_diagnosis"] == "generated-expectation"
    assert "generated_expected" not in retry["generated_test_failures"][0]
    assert "PRIVATE-EVALUATOR-SENTINEL" not in transport.requests[1]["input"]
    generator.feedback = [generator.feedback[1]]
    generator.previous_source = artifact["source"]
    generator.generate(spec, tmp_path / "private-only-retry" / "echo-integer")
    private_retry = json.loads(transport.requests[2]["input"])
    assert private_retry["operation"] == "repair"
    assert private_retry["generated_test_failures"] == []
    assert "PRIVATE-EVALUATOR-SENTINEL" not in transport.requests[2]["input"]


@pytest.mark.parametrize(
    "examples", [["wrong-root"], [0, 1, 2, 3], ["password=do-not-send"], [float("nan")]]
)
def test_invalid_operator_examples_are_refused_before_inference(tmp_path, examples):
    transport = RecordedTransport([])
    backend = ResponsesBackend(ModelConfig(model="fixture"), transport)
    spec = general_plan(
        "Echo an integer",
        "echo-integer",
        "python-json",
        inputs={"type": "integer"},
        outputs={"type": "integer"},
    )
    with pytest.raises(ForgeError):
        ModelGenerator(backend, example_inputs=examples).generate(spec, tmp_path / "echo-integer")
    assert not transport.requests


@pytest.mark.parametrize(
    "envelope",
    [[], {"choices": [0]}, {"choices": [{"finish_reason": "stop", "message": None}], "usage": {}}],
)
def test_malformed_local_envelopes_produce_controlled_refusals(monkeypatch, envelope):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(json.dumps(envelope).encode())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    transport = LocalTransport("http://127.0.0.1:31871/v1/chat/completions", approved=True)
    with pytest.raises(ForgeError):
        transport.post(
            {
                "model": "offline-unit",
                "instructions": "test",
                "input": "{}",
                "max_output_tokens": 64,
                "text": {"format": {"name": "test", "schema": {}}},
            },
            timeout=1,
        )


@pytest.mark.parametrize("operation", ["plan", "build"])
def test_local_wire_keeps_planning_separate_from_program_generation(monkeypatch, operation):
    observed = []

    class Opener:
        def open(self, request, timeout):
            observed.append(json.loads(request.data))
            return io.BytesIO(
                json.dumps(
                    {
                        "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                    }
                ).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    LocalTransport("http://127.0.0.1:31871/v1/chat/completions", approved=True).post(
        {
            "model": "wire-fixture",
            "instructions": "Return the requested object.",
            "input": json.dumps({"operation": operation}),
            "max_output_tokens": 64,
            "text": {"format": {"name": "wire-test", "schema": {"type": "object"}}},
        },
        timeout=1,
    )
    hint = "Write actual source code in source"
    assert (hint in observed[0]["messages"][0]["content"]) == (operation == "build")
