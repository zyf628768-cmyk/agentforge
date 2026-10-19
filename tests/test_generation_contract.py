import json
from pathlib import Path

from agentforge.core import read_json
from agentforge.providers import ModelConfig, ModelGenerator, RecordedTransport, ResponsesBackend


def test_generator_schema_enforces_target_paths_before_builder(tmp_path):
    fixtures = Path(__file__).resolve().parents[1] / "examples/v02"
    transport = RecordedTransport(read_json(fixtures / "csv-summary.response.json")["responses"])
    generator = ModelGenerator(ResponsesBackend(ModelConfig(model="offline"), transport))
    generator.generate(read_json(fixtures / "csv-summary.plan.json"), tmp_path / "csv-summary")
    schema = transport.requests[0]["text"]["format"]["schema"]
    allowed = schema["properties"]["files"]["items"]["properties"]["path"]["enum"]
    assert set(allowed) == {
        "scripts/main.py",
        "README.md",
        "tests/cases.json",
        "examples/input.json",
        "examples/output.json",
    }
    assert "main.py" not in allowed
    assert generator.last_bundle["files"]
    assert json.loads(transport.requests[0]["input"])["required_paths"] == allowed


def test_local_typed_engineering_serializes_json_without_manual_code_repair(tmp_path):
    from agentforge.spec import general_plan

    value = {
        "contract_summary": "Input is an integer array. Return its integer sum; empty input sums to zero.",
        "source": "import json,sys\njson.dump(sum(json.load(sys.stdin)),sys.stdout)\n",
        "readme": "Sum integers",
        "tests": [{"id": "empty", "input": [], "expected": 0}],
        "example_input": [1, 2],
        "example_output": 3,
    }
    response = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }
    transport = RecordedTransport([response])
    transport.kind = "local-llama.cpp"
    spec = general_plan(
        "Sum integers",
        "sum-integers",
        "python-json",
        inputs={"type": "array", "items": {"type": "integer"}},
        outputs={"type": "integer"},
    )
    generator = ModelGenerator(ResponsesBackend(ModelConfig(model="test"), transport))
    root = generator.generate(spec, tmp_path / "sum-integers")
    assert read_json(root / "tests/cases.json") == value["tests"]
    assert (root / "scripts/main.py").read_text() == value["source"]
    assert "export run(i32" not in transport.requests[0]["instructions"]
