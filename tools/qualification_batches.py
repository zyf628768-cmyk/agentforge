"""Keep qualification runs within the engine's 32-case independent-suite limit."""

from agentforge.contracts import contract_hash
from agentforge.core import write_json
from agentforge.testing import evaluate


def evaluate_batches(artifact, spec, cases, prefix, config, *, timeout=30):
    if not cases or len(cases) > 256:
        raise ValueError("Require 1..256 qualification cases, evaluated in bounded batches")
    reports, batches = [], []
    for offset in range(0, len(cases), 32):
        evaluation = prefix.with_name(prefix.name + f".part-{offset // 32}.independent.json")
        report_path = prefix.with_name(prefix.name + f".part-{offset // 32}.report.json")
        write_json(
            evaluation, {"contract_hash": contract_hash(spec), "cases": cases[offset : offset + 32]}
        )
        report = evaluate(
            artifact,
            report_path,
            timeout=timeout,
            evaluation_path=evaluation,
            container_config=config,
        )
        reports.append(report)
        batches.append(
            {
                "evaluation": str(evaluation),
                "report": str(report_path),
                "cases": len(cases[offset : offset + 32]),
            }
        )
    total = sum(report["metrics"]["tests_total"] for report in reports)
    passed = sum(report["metrics"]["tests_passed"] for report in reports)
    valid = [case for report in reports for case in report["cases"] if not case["expects_error"]]
    metrics = {
        "tests_total": total,
        "tests_passed": passed,
        "pass_rate": passed / total if total else 0,
        "functional_correctness": sum(case["passed"] for case in valid) / len(valid)
        if valid
        else 0,
        "max_guest_memory_bytes": max(
            report["metrics"]["max_guest_memory_bytes"] for report in reports
        ),
        "safety_passed": all(report["metrics"]["safety_passed"] for report in reports),
        "regression_passed": all(report["metrics"]["regression_passed"] for report in reports),
    }
    for name in ("seconds", "fuel_used", "primary_fuel_used"):
        metrics[name] = sum(report["metrics"][name] for report in reports)
    return {
        "status": "passed" if all(report["status"] == "passed" for report in reports) else "failed",
        "artifact_hash": reports[0]["artifact_hash"],
        "independent_cases": len(cases),
        "metrics": metrics,
        "batches": batches,
        "note": "Generated and integration checks repeat in each batch; unique independent cases are counted separately.",
    }
