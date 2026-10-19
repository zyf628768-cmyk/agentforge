import json
import random
from pathlib import Path

import pytest

from agentforge.artifacts import BundleGenerator, safe_bundle
from agentforge.contracts import check_schema, contract_hash
from agentforge.core import ForgeError, read_json, tree_hash, write_json
from agentforge.evolution import evolve
from agentforge.providers import ModelConfig, ModelGenerator, RecordedTransport, ResponsesBackend
from agentforge.registry import Registry
from agentforge.sandbox import run_skill
from agentforge.spec import general_plan
from agentforge.testing import evaluate

FIXTURES = Path(__file__).resolve().parents[1] / "examples/v02"


def build(tmp_path, name="integer-stats", broken=False):
    spec = read_json(FIXTURES / f"{name}.plan.json")
    bundle = read_json(FIXTURES / f"{name}{'.broken' if broken else ''}.bundle.json")
    root = BundleGenerator(bundle).generate(spec, tmp_path / name)
    return root, FIXTURES / f"{name}.evaluation.json"


@pytest.mark.parametrize("name", ["integer-stats", "rot13"])
def test_generic_execution_independent_verification_and_os_limits(tmp_path, name):
    root, independent = build(tmp_path, name)
    report = evaluate(root, evaluation_path=independent)
    assert report["status"] == "passed"
    assert report["metrics"]["tests_total"] == 6
    assert report["execution"]["os_limits"]["enforced"]
    unverified = evaluate(root)
    assert unverified["status"] == "unverified"
    assert not unverified["metrics"]["regression_passed"]
    assert run_skill(root, read_json(root / "examples/input.json"))["results"][0][
        "output"
    ] == read_json(root / "examples/output.json")


def test_numeric_differential_random_inputs(tmp_path):
    root, _ = build(tmp_path)
    from agentforge.sandbox import Sandbox

    spec = read_json(root / "spec.json")
    generator = random.Random(1337)
    values = [
        [generator.randint(-1000000, 1000000) for _ in range(generator.randrange(20))]
        for _ in range(30)
    ]
    result = Sandbox().execute((root / "scripts/main.wasm").read_bytes(), values, contract=spec)
    for value, actual in zip(values, result["results"], strict=True):
        assert actual["ok"] and actual["output"] == {"sum": sum(value), "count": len(value)}


def test_generic_model_repair_and_regression_retention(tmp_path):
    broken, independent = build(tmp_path / "broken", broken=True)
    before_hash = tree_hash(broken)
    before = evaluate(broken, evaluation_path=independent)
    assert before["status"] == "failed"
    responses = read_json(FIXTURES / "integer-stats.response.json")["responses"]
    transport = RecordedTransport(responses)
    backend = ResponsesBackend(ModelConfig(model="offline-fixture"), transport)
    registry = Registry(tmp_path / "registry")
    result = evolve(
        broken,
        tmp_path / "repair",
        registry,
        generator=ModelGenerator(backend),
        evaluation_path=independent,
    )
    assert result["accepted"] and result["cost_usd"] == 0
    assert tree_hash(broken) == before_hash
    request = json.loads(transport.requests[0]["input"])
    assert request["generated_test_failures"]
    assert all(c["suite"] != "independent" for c in request["generated_test_failures"])
    assert "private-mixed" not in json.dumps(transport.requests)
    repaired = Path(result["attempts"][0]["path"])
    assert evaluate(repaired, evaluation_path=independent)["status"] == "passed"
    active_hash = registry.show("integer-stats")["hash"]
    regression = evolve(
        repaired,
        tmp_path / "regression",
        registry,
        mode="optimize",
        generator=BundleGenerator.from_file(FIXTURES / "integer-stats.broken.bundle.json"),
        evaluation_path=independent,
    )
    assert not regression["accepted"]
    assert registry.show("integer-stats")["hash"] == active_hash


def test_evaluator_contract_binding_and_candidate_owned_set_refused(tmp_path):
    root, independent = build(tmp_path)
    value = read_json(independent)
    value["contract_hash"] = "different"
    write_json(tmp_path / "wrong.json", value)
    with pytest.raises(ForgeError, match="sealed contract"):
        evaluate(root, evaluation_path=tmp_path / "wrong.json")
    write_json(root / "candidate-holdout.json", read_json(independent))
    with pytest.raises(ForgeError, match="outside"):
        evaluate(root, evaluation_path=root / "candidate-holdout.json")


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "scripts/../../escape.py",
        "C:/escape.py",
        "scripts/CON.py",
        "scripts/.hidden.py",
        "manifest.json",
        "scripts/main.wasm",
        "schemas/input.json",
    ],
)
def test_artifact_path_and_metadata_attacks_rejected(path):
    bundle = read_json(FIXTURES / "integer-stats.bundle.json")
    bundle["files"].append({"path": path, "content": "untrusted"})
    with pytest.raises(ForgeError):
        safe_bundle(bundle, "wasm-json")


def test_case_collisions_and_partial_publication(tmp_path):
    bundle = read_json(FIXTURES / "integer-stats.bundle.json")
    bundle["files"].append({"path": "SCRIPTS/MAIN.WAT", "content": "bad"})
    with pytest.raises(ForgeError):
        safe_bundle(bundle, "wasm-json")
    bundle["files"].pop()
    bundle["files"][0]["content"] = "(not wasm)"
    spec = read_json(FIXTURES / "integer-stats.plan.json")
    target = tmp_path / "integer-stats"
    with pytest.raises(ForgeError):
        BundleGenerator(bundle).generate(spec, target)
    assert not target.exists()


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.invalid/schema"},
        {"$ref": "#/loop"},
        {"pattern": "(a+)+$"},
        {"anyOf": [{}]},
        {"uniqueItems": True},
    ],
)
def test_schema_network_and_complexity_features_denied(schema):
    with pytest.raises(ForgeError):
        check_schema(schema)


def test_arbitrary_goal_is_supported_as_spec_not_claimed_as_verified():
    spec = general_plan(
        "Validate a structured invoice and compute totals", "invoice-checker", "python-json"
    )
    assert spec["goal"].startswith("Validate")
    assert spec["kind"] == "python-json"
    assert len(contract_hash(spec)) == 64


def test_candidate_cannot_expect_guest_trap_as_valid_behavior(tmp_path):
    root, _ = build(tmp_path)
    write_json(root / "tests/cases.json", [{"id": "trap", "input": [1], "error_type": "Trap"}])
    with pytest.raises(ForgeError, match="ValidationError"):
        evaluate(root)


def test_json_boolean_cannot_impersonate_a_number(tmp_path):
    spec = general_plan("Return integer one", "constant", outputs={})
    bundle = {
        "files": [
            {
                "path": "scripts/main.wat",
                "content": '(module (memory (export "memory") 1 1) (data (i32.const 32768) "true") (func (export "run") (param i32) (result i32) i32.const 4))',
            },
            {"path": "README.md", "content": "Return one"},
            {"path": "tests/cases.json", "content": '[{"id":"one","input":{},"expected":1}]'},
            {"path": "examples/input.json", "content": "{}"},
            {"path": "examples/output.json", "content": "1"},
        ]
    }
    root = BundleGenerator(bundle).generate(spec, tmp_path / "constant")
    assert evaluate(root)["status"] == "failed"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_rejected(tmp_path, value):
    (tmp_path / "input.json").write_text(value, encoding="utf-8")
    with pytest.raises(ForgeError, match="Non-finite"):
        read_json(tmp_path / "input.json")


def test_registry_redacts_independent_evidence_at_rest(tmp_path):
    root, independent = build(tmp_path / "skill")
    report = evaluate(root, evaluation_path=independent)
    report["operator_note"] = "password=do-not-persist"
    registry = Registry(tmp_path / "registry")
    registry.register(root, report)
    assert "do-not-persist" not in registry.db.read_bytes().decode("utf-8", errors="ignore")


def test_generators_and_evidence_preserve_existing_baseline(tmp_path):
    root, independent = build(tmp_path / "stable")
    digest = tree_hash(root)
    with pytest.raises(ForgeError, match="inside"):
        BundleGenerator.from_file(FIXTURES / "integer-stats.bundle.json").generate(
            read_json(root / "spec.json"), root / "nested" / "integer-stats"
        )
    with pytest.raises(ForgeError, match="outside"):
        evolve(
            root, root / "evolution", Registry(tmp_path / "registry"), evaluation_path=independent
        )
    assert tree_hash(root) == digest


def test_registry_activation_is_compare_and_swap(tmp_path):
    root, independent = build(tmp_path / "skill")
    registry = Registry(tmp_path / "registry")
    registry.register(root, evaluate(root, evaluation_path=independent))
    registry.activate("integer-stats", "0.2.0", expected_active=None)
    with pytest.raises(ForgeError, match="changed"):
        registry.activate("integer-stats", "0.2.0", rollback=True, expected_active=None)
    assert registry.show("integer-stats")["version"] == "0.2.0"


def test_output_schema_errors_cannot_count_as_input_rejection(tmp_path):
    bundle = read_json(FIXTURES / "integer-stats.bundle.json")
    case_file = next(f for f in bundle["files"] if f["path"] == "tests/cases.json")
    case_file["content"] = (
        '[{"id":"incorrect-rejection","input":[1],"error_type":"ValidationError"}]'
    )
    with pytest.raises(ForgeError, match="actually violate"):
        BundleGenerator(bundle).generate(
            read_json(FIXTURES / "integer-stats.plan.json"), tmp_path / "integer-stats"
        )
