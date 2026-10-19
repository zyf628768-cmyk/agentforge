"""Re-evaluate unchanged real-model artifacts on fresh seeds; no model requests."""

import argparse
import hashlib
import json
from pathlib import Path

from domain_cases import domains
from qualification_batches import evaluate_batches

from agentforge.core import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output must be new")
    args.output.mkdir(parents=True)
    artifacts = {}
    for summary_path in args.summary:
        summary = read_json(summary_path)
        if summary.get("fixture_generation") is not False:
            parser.error("Require actual model-generation evidence, not authored fixtures")
        for trial in summary["domains"]:
            if trial["status"] == "passed":
                artifacts[trial["name"]] = Path(
                    trial.get("accepted_artifact") or summary_path.parent / "skills" / trial["name"]
                )
    config = read_json(args.runtime_config)
    seeds = [19317, 62039, 90821, 45197]
    goals = domains()
    result = {"model_requests": 0, "fresh_seeds": seeds, "domains": []}
    for goal in goals:
        name = goal["name"]
        if name not in artifacts:
            result["domains"].append(
                {"name": name, "status": "blocked", "reason": "No accepted real-model artifact"}
            )
            continue
        root = artifacts[name]
        spec = read_json(root / "spec.json")
        allowed_goals = {goal["goal"]}
        if name == "merge-intervals":
            allowed_goals.add(
                "Merge overlapping OR TOUCHING integer intervals. Input array of [start,end] pairs with start<=end. Sort ascending and return merged array. Empty => []."
            )
        if spec["goal"] not in allowed_goals:
            raise ValueError("Qualification goal changed: " + name)
        unique = {}
        for seed in seeds:
            candidate = next(d for d in domains(seed) if d["name"] == name)
            for value, expected in candidate["cases"]:
                key = json.dumps(value, sort_keys=True, ensure_ascii=True)
                if key in unique and unique[key][1] != expected:
                    raise ValueError("Independent oracles disagree for the same input")
                unique[key] = (value, expected)
        cases = [
            {"id": f"fresh-{i}", "input": v, "expected": e}
            for i, (v, e) in enumerate(unique.values())
        ]
        cases += [
            {"id": "fresh-invalid-null", "input": None, "error_type": "ValidationError"},
            {
                "id": "fresh-invalid-root",
                "input": {} if spec["inputs"]["type"] == "array" else [],
                "error_type": "ValidationError",
            },
        ]
        report_path = args.output / (name + ".report.json")
        report = evaluate_batches(root, spec, cases, args.output / name, config, timeout=30)
        write_json(report_path, report, safe=True)
        item = {
            "name": name,
            "status": report["status"],
            "unique_cases": len(cases),
            "artifact": str(root),
            "artifact_hash": report["artifact_hash"],
            "case_set_sha256": hashlib.sha256(
                json.dumps(cases, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest(),
            "batches": report["batches"],
            "metrics": report["metrics"],
            "report": str(report_path),
            "original_goal": spec["goal"],
            "precise_evaluation_goal": goal["goal"],
        }
        result["domains"].append(item)
        write_json(args.output / "summary.json", result, safe=True)
        print(
            name,
            item["status"],
            report["metrics"]["tests_passed"],
            "/",
            report["metrics"]["tests_total"],
            flush=True,
        )
    result["status"] = (
        "passed"
        if len(result["domains"]) == len(goals)
        and all(d["status"] == "passed" for d in result["domains"])
        else "failed"
    )
    result["independent_cases"] = sum(d.get("unique_cases", 0) for d in result["domains"])
    write_json(args.output / "summary.json", result, safe=True)
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
