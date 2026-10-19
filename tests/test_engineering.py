import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

from agentforge.core import ForgeError, read_json, redact, tree_hash, write_json
from agentforge.evolution import Budget, classify, evolve
from agentforge.generator import Generator, OfflineGenerator
from agentforge.registry import Registry
from agentforge.sandbox import Sandbox, SandboxUnavailable, run_skill
from agentforge.spec import plan, validate
from agentforge.testing import compare, evaluate
from agentforge.validation import inspect_skill


def test_spec_parsing_editing_and_schema(tmp_path):
    spec = plan("清洗文本并保留大小写")
    spec["steps"].append("Human review of examples")
    write_json(tmp_path / "plan.json", spec)
    assert validate(read_json(tmp_path / "plan.json")) == spec
    spec["dependencies"] = ["requests"]
    with pytest.raises(ForgeError):
        validate(spec)


@pytest.mark.parametrize("goal", ["Deploy production", "Write a spreadsheet"])
def test_unsupported_goals_rejected(goal):
    with pytest.raises(ForgeError, match="supports text cleaning only"):
        plan(goal)


def test_project_and_generator_protocol(make_skill, tmp_path):
    # An independently implemented adapter exercises the public generator contract.
    class Adapter:
        def generate(self, spec, destination, variant="correct"):
            return OfflineGenerator().generate(spec, destination, variant)

    backend: Generator = Adapter()
    root = backend.generate(plan("Clean text"), tmp_path / "adapter" / "text-cleaner")
    for relative in (
        "SKILL.md",
        "scripts/clean.wasm",
        "scripts/run.py",
        "config.json",
        "tests/test_skill.py",
        "tests/cases.json",
        "README.md",
        "schemas/input.json",
        "examples/output.json",
    ):
        assert (root / relative).is_file()
    assert inspect_skill(root)["passed"]
    assert evaluate(root)["status"] == "passed"
    with pytest.raises(ForgeError, match="exists"):
        backend.generate(plan("Clean text"), root)


def test_skill_spec_integrity_and_dependency_checks(make_skill):
    root = make_skill()
    manifest = read_json(root / "manifest.json")
    manifest["dependencies"] = ["unavailable-package"]
    write_json(root / "manifest.json", manifest)
    assert not inspect_skill(root)["passed"]
    assert evaluate(root)["status"] == "blocked"


def test_real_engine_execution_and_evidence(make_skill, tmp_path):
    root = make_skill()
    report = evaluate(root, tmp_path / "evidence.json")
    assert report["status"] == "passed"
    assert report["metrics"]["tests_total"] == 12
    assert report["metrics"]["fuel_used"] > 0
    assert report["execution"]["exit_code"] == 0
    assert "agentforge._worker" in report["execution"]["command"]
    assert report["execution"]["isolation"] == "wasmtime-no-imports"
    assert {"unit", "integration", "independent"} == {c["suite"] for c in report["cases"]}
    evidence = run_skill(root, {"text": "  Hello\t世界\n "})
    assert evidence["results"][0]["output"] == {"text": "Hello 世界"}


def test_failure_identification_and_controlled_repair(make_skill, tmp_path):
    root = make_skill("bug")
    digest = tree_hash(root)
    before = evaluate(root)
    assert before["status"] == "failed"
    assert any(c["id"] == "unit-tab" and not c["passed"] for c in before["cases"])
    assert classify(before)["category"] == "functional"
    registry = Registry(tmp_path / "registry")
    result = evolve(root, tmp_path / "repair", registry)
    assert result["accepted"]
    assert len(result["attempts"]) == 1
    repaired = Path(result["attempts"][0]["path"])
    after = evaluate(repaired)
    assert after["status"] == "passed"
    assert compare(before, after)["accepted"]
    assert registry.show("text-cleaner")["version"] == "0.1.1"
    assert tree_hash(root) == digest


def test_regression_rejected_and_stable_retained(make_skill, tmp_path):
    root = make_skill()
    registry = Registry(tmp_path / "registry")
    registry.register(root, evaluate(root))
    registry.activate("text-cleaner", "0.1.0")
    digest = tree_hash(root)
    result = evolve(root, tmp_path / "regression", registry, mode="regression")
    assert not result["accepted"]
    assert result["attempts"][0]["comparison"]["reasons"]
    assert registry.show("text-cleaner")["version"] == "0.1.0"
    assert registry.show("text-cleaner", "0.1.1")["status"] == "rejected"
    assert tree_hash(root) == digest


def test_independent_set_not_overridden_by_candidate(make_skill):
    root = make_skill("regression")
    write_json(
        root / "tests/cases.json",
        [{"id": "cheating", "input": {"text": " ABC "}, "expected": {"text": "abc"}}],
    )
    report = evaluate(root)
    assert report["cases"][0]["passed"]
    assert report["status"] == "failed"
    assert not report["metrics"]["regression_passed"]


def test_baseline_tests_cannot_be_deleted(make_skill):
    baseline_root = make_skill()
    cases = read_json(baseline_root / "tests/cases.json")
    cases.append(
        {
            "id": "custom-acceptance",
            "input": {"text": " Custom  CASE "},
            "expected": {"text": "Custom CASE"},
        }
    )
    write_json(baseline_root / "tests/cases.json", cases)
    baseline = evaluate(baseline_root)
    candidate = make_skill(version="0.1.1")
    unprotected = evaluate(candidate)
    assert not compare(baseline, unprotected)["accepted"]
    protected = evaluate(candidate, regression_cases=baseline["cases"])
    assert compare(baseline, protected)["accepted"]
    assert any(c["id"] == "baseline-custom-acceptance" for c in protected["cases"])


def test_registry_sqlite_git_export_and_rollback(make_skill, tmp_path):
    first = make_skill(version="0.1.0")
    second = make_skill(version="0.1.1")
    registry = Registry(tmp_path / "registry")
    for root in (first, second):
        registry.register(root, evaluate(root))
    registry.activate("text-cleaner", "0.1.0")
    registry.activate("text-cleaner", "0.1.1", rollback=True)
    restored = registry.activate("text-cleaner", "0.1.0", rollback=True)
    assert len(restored["git_commit"]) == 40
    assert registry.show("text-cleaner")["hash"] == tree_hash(first)
    exported = registry.export("text-cleaner", "0.1.0", tmp_path / "export" / "text-cleaner")
    assert tree_hash(exported) == tree_hash(first)
    assert evaluate(exported)["status"] == "passed"
    assert len(registry.list("cleaner")) == 2
    assert not registry.list("'; DROP TABLE versions; --")
    with pytest.raises(ForgeError, match="already registered"):
        registry.register(first, evaluate(first))


def test_registry_windows_long_paths(make_skill, tmp_path):
    root = make_skill()
    # Keep real paths below the OS directory limit while Git's ambiguous
    # revision:path stat probe would exceed MAX_PATH without core.longpaths.
    padding = "p" * max(1, 170 - len(str(tmp_path)) - len("/registry") - 1)
    registry = Registry(tmp_path / padding / "registry")
    registry.register(root, evaluate(root))
    assert registry.activate("text-cleaner", "0.1.0")["active_version"] == "0.1.0"
    exported = registry.export("text-cleaner", "0.1.0", tmp_path / "long-export/text-cleaner")
    assert tree_hash(exported) == tree_hash(root)


def test_changed_artifact_cannot_register_old_results(make_skill, tmp_path):
    root = make_skill()
    report = evaluate(root)
    (root / "README.md").write_text("Changed after test", encoding="utf-8")
    with pytest.raises(ForgeError, match="changed"):
        Registry(tmp_path / "registry").register(root, report)


def test_no_evidence_written_inside_artifact(make_skill):
    root = make_skill()
    with pytest.raises(ForgeError, match="outside"):
        evaluate(root, root / "report.json")


@pytest.mark.parametrize("iterations,seconds", [(0, 30), (2, 0.00001)])
def test_loop_and_time_limits(make_skill, tmp_path, iterations, seconds):
    root = make_skill("bug")
    result = evolve(
        root,
        tmp_path / "limited",
        Registry(tmp_path / "registry"),
        budget=Budget(iterations, seconds, 0),
    )
    assert not result["accepted"]
    assert len(result["attempts"]) == 0
    assert result["stop_reason"] in {"iteration-budget", "time-budget", "safety-blocked"}
    assert result["cost_usd"] == 0


@pytest.mark.parametrize("args", [(-1, 30, 0), (21, 30, 0), (2, 0, 0), (2, 30, -1)])
def test_budget_invalid(args):
    with pytest.raises(ForgeError):
        Budget(*args)


def test_sensitive_information_filtering_and_rejection(make_skill):
    secret = "sk-" + "exampleSecret123456"
    assert secret not in json.dumps(redact({"api_key": secret, "message": "token=abc123"}))
    with pytest.raises(ForgeError, match="sensitive"):
        plan("Clean text with api_key=" + secret)
    root = make_skill()
    (root / "README.md").write_text("password=do-not-log-this", encoding="utf-8")
    assert not inspect_skill(root)["passed"]


def test_sandbox_unavailable_refuses_without_process(monkeypatch, make_skill):
    root = make_skill()
    monkeypatch.setattr(Sandbox, "available", staticmethod(lambda: False))

    def forbidden(*args, **kwargs):
        raise AssertionError("A process must not run without sandbox")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(SandboxUnavailable):
        Sandbox().execute(b"\x00asm", [])
    report = evaluate(root)
    assert report["status"] == "blocked"
    assert not report["cases"]
    assert report["execution"]["command"] is None


def test_generated_python_is_never_executed(make_skill, tmp_path):
    root = make_skill()
    marker = tmp_path / "HOST-EXECUTION"
    (root / "scripts/run.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n", encoding="utf-8"
    )
    assert evaluate(root)["status"] == "passed"
    assert not marker.exists()


@pytest.mark.parametrize(
    "command", ["init", "plan", "build", "test", "evolve", "compare", "registry", "doctor", "run"]
)
def test_all_cli_help(command):
    result = subprocess.run(
        [sys.executable, "-m", "agentforge", command, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_invalid_input_is_real_validation(make_skill):
    root = make_skill()
    result = Sandbox().execute((root / "scripts/clean.wasm").read_bytes(), [{"text": 5}])
    assert not result["results"][0]["ok"]
    assert result["results"][0]["error_type"] == ValidationError.__name__
