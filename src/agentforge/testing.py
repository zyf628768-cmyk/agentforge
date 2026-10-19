"""Evidence-based evaluation; candidate-provided claims do not determine status."""

from __future__ import annotations

import hashlib
import json
import time
from importlib.resources import files
from pathlib import Path

from .contracts import check_cases, contract_hash
from .core import ForgeError, json_equal, read_json, tree_hash, write_json
from .sandbox import Sandbox, SandboxUnavailable
from .validation import inspect_skill


def evaluate(
    root: Path,
    report_path: Path | None = None,
    *,
    timeout: float = 15.0,
    regression_cases: list[dict] | None = None,
    evaluation_path: Path | None = None,
    container_config: dict | None = None,
) -> dict:
    if report_path and report_path.resolve().is_relative_to(root.resolve()):
        raise ForgeError("Evidence must be stored outside the immutable Skill directory")
    started = time.monotonic()
    checks = inspect_skill(root)
    spec = read_json(root / "spec.json")
    generic = spec["kind"] != "text-cleaner"
    report = {
        "skill": str(root.resolve()),
        "artifact_hash": tree_hash(root),
        "status": "blocked",
        "checks": checks,
        "cases": [],
        "execution": None,
        "evaluator": "agentforge-independent-v1",
        "cost_usd": 0.0,
        "contract_hash": contract_hash(spec),
        "verification": "generated-only" if generic and not evaluation_path else "independent",
    }
    if checks["passed"]:
        cases = read_json(root / "tests/cases.json")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
            raise ForgeError("Require 1..32 generated JSON test cases")
        if generic:
            holdout = []
            if evaluation_path:
                if evaluation_path.resolve().is_relative_to(root.resolve()):
                    raise ForgeError(
                        "Independent evaluation must be outside the candidate artifact"
                    )
                evaluation = read_json(evaluation_path)
                if (
                    evaluation.get("contract_hash") != contract_hash(spec)
                    or not isinstance(evaluation.get("cases"), list)
                    or not 1 <= len(evaluation["cases"]) <= 32
                ):
                    raise ForgeError(
                        "Independent evaluation must match the sealed contract and contain 1..32 cases"
                    )
                holdout = evaluation["cases"]
            holdout_bytes = json.dumps(holdout, sort_keys=True).encode()
        else:
            holdout_bytes = files("agentforge").joinpath("data/holdout.json").read_bytes()
        report["holdout_hash"] = hashlib.sha256(holdout_bytes).hexdigest()
        cases = [{**case, "suite": "unit"} for case in cases] + [
            {**case, "suite": "independent"} for case in json.loads(holdout_bytes)
        ]
        # Integration uses the same public input/output contract as `run`.
        cases.append(
            {
                "id": "example-integration",
                "suite": "integration",
                "input": read_json(root / "examples/input.json"),
                "expected": read_json(root / "examples/output.json"),
            }
        )
        # Re-run previously passing baseline behavior on the candidate, including
        # tests which its generator removed or changed.
        for old in regression_cases or []:
            if not old["passed"]:
                continue
            if any(
                json_equal(current["input"], old["input"])
                and (
                    json_equal(current.get("expected"), old["expected"])
                    if not old.get("expects_error")
                    else current.get("error_type") == old["expected"]
                )
                for current in cases
            ):
                continue
            case = {
                "id": "baseline-" + old["id"],
                "suite": "baseline-regression",
                "input": old["input"],
            }
            case["error_type" if old.get("expects_error") else "expected"] = old["expected"]
            cases.append(case)
        if any(
            not isinstance(c, dict)
            or "id" not in c
            or "input" not in c
            or not ("expected" in c or "error_type" in c)
            for c in cases
        ):
            raise ForgeError("Malformed test case")
        identifiers = set()
        for case in cases:
            if (
                not isinstance(case["id"], str)
                or not 1 <= len(case["id"]) <= 160
                or case["id"] in identifiers
            ):
                raise ForgeError("Case IDs must be unique bounded strings")
            identifiers.add(case["id"])
            if ("expected" in case) == ("error_type" in case) or (
                "error_type" in case and case["error_type"] != "ValidationError"
            ):
                raise ForgeError("Cases require expected output or a schema ValidationError")
            if len(json.dumps(case, allow_nan=False).encode()) > 65000:
                raise ForgeError("Case exceeds byte budget")
        check_cases(cases, spec)
        try:
            if spec["kind"] == "python-json":
                from .python_wasi import python_runtime

                execution = python_runtime(container_config, timeout=timeout).execute(
                    root, [c["input"] for c in cases], spec
                )
            else:
                manifest = read_json(root / "manifest.json")
                execution = Sandbox(timeout=timeout).execute(
                    (root / manifest["entrypoint"]).read_bytes(),
                    [c["input"] for c in cases],
                    contract=spec if generic else None,
                )
        except SandboxUnavailable as exc:
            execution = {
                "status": "blocked",
                "error": str(exc),
                "results": [],
                "command": None,
                "exit_code": None,
            }
        report["execution"] = execution
        if execution["status"] == "completed" and len(execution["results"]) == len(cases):
            for case, actual in zip(cases, execution["results"], strict=True):
                passed = (
                    (actual.get("ok") and json_equal(actual.get("output"), case.get("expected")))
                    if "expected" in case
                    else (not actual.get("ok") and actual.get("error_type") == case["error_type"])
                )
                report["cases"].append(
                    {
                        "id": case["id"],
                        "suite": case["suite"],
                        "passed": bool(passed),
                        "input": case["input"],
                        "expected": case.get("expected", case.get("error_type")),
                        "expects_error": "error_type" in case,
                        "actual": actual,
                    }
                )
            report["status"] = "passed" if all(c["passed"] for c in report["cases"]) else "failed"
            if report["status"] == "passed" and generic and not evaluation_path:
                report["status"] = "unverified"
    total = len(report["cases"])
    passed = sum(c["passed"] for c in report["cases"])
    valid = [c for c in report["cases"] if not c["id"].startswith("invalid-")]
    report["metrics"] = {
        "tests_total": total,
        "tests_passed": passed,
        "pass_rate": passed / total if total else 0,
        "functional_correctness": sum(c["passed"] for c in valid) / len(valid) if valid else 0,
        "seconds": time.monotonic() - started,
        "fuel_used": sum(c["actual"].get("fuel_used", 0) for c in report["cases"]),
        "primary_fuel_used": sum(
            c["actual"].get("fuel_used", 0)
            for c in report["cases"]
            if c["suite"] != "baseline-regression"
        ),
        "max_guest_memory_bytes": max(
            (c["actual"].get("memory_bytes", 0) for c in report["cases"]), default=0
        ),
        "safety_passed": checks["passed"] and report["status"] != "blocked",
        "regression_passed": bool(total)
        and report["verification"] == "independent"
        and all(c["passed"] for c in report["cases"] if c["suite"] == "independent"),
    }
    if report_path:
        write_json(report_path, report, safe=True)
    return report


def compare(baseline: dict, candidate: dict) -> dict:
    reasons = []
    if baseline.get("contract_hash") != candidate.get("contract_hash"):
        reasons.append("Input/output contracts differ")
    if baseline.get("holdout_hash") != candidate.get("holdout_hash"):
        reasons.append("Independent evaluation set differs")
    if candidate["status"] != "passed":
        reasons.append("Candidate did not pass every acceptance/regression check")
    for key in ("pass_rate", "functional_correctness"):
        if candidate["metrics"][key] < baseline["metrics"][key]:
            reasons.append(key + " decreased")
    if not candidate["metrics"]["safety_passed"]:
        reasons.append("Safety checks failed or execution unavailable")
    for previous in baseline["cases"]:
        if previous["passed"] and not any(
            current["passed"]
            and json_equal(current["input"], previous["input"])
            and json_equal(current["expected"], previous["expected"])
            and current.get("expects_error") == previous.get("expects_error")
            for current in candidate["cases"]
        ):
            reasons.append("Baseline behavior missing or regressed: " + previous["id"])
    if candidate["metrics"]["primary_fuel_used"] > max(
        1000, baseline["metrics"]["primary_fuel_used"] * 1.25
    ):
        reasons.append("Instruction cost exceeded 25% regression allowance")
    if candidate["metrics"]["seconds"] > max(2.0, baseline["metrics"]["seconds"] * 3):
        reasons.append("Execution time exceeded 3x / 2s noise allowance")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "baseline_hash": baseline["artifact_hash"],
        "candidate_hash": candidate["artifact_hash"],
        "baseline": baseline["metrics"],
        "candidate": candidate["metrics"],
    }
