"""Actual free model planning, source generation and independent WASI acceptance."""

import argparse
import json
import random
from pathlib import Path

from qualification_batches import evaluate_batches

from agentforge.billing import BudgetLedger
from agentforge.core import read_json, write_json
from agentforge.local_model import LocalTransport
from agentforge.providers import ModelConfig, ModelGenerator, ResponsesBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-endpoint", required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--approve-local-model", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve existing qualification evidence")
    config = ModelConfig(**read_json(args.model_config))
    if config.max_cost_usd or config.input_usd_per_million or config.output_usd_per_million:
        parser.error("This qualification permits explicitly approved free local inference only")
    args.output.mkdir(parents=True)
    goal = (
        "Return an object containing count, the number of ASCII digits (0 through 9) "
        "in the input string; ignore every other character."
    )
    rng = random.Random(726193)
    inputs = ["", "abc", "0123456789", "a0b9", "１２٣٤١", "💡x5é", '\\"123'] + [
        "".join(rng.choices("abcXYZ0123456789é١💡", k=rng.randrange(40))) for _ in range(33)
    ]
    # Independent expected values are fixed before either inference call.
    cases = [
        {
            "id": f"independent-{i}",
            "input": value,
            "expected": {"count": sum("0" <= c <= "9" for c in value)},
        }
        for i, value in enumerate(inputs)
    ]
    cases += [
        {"id": "invalid-null", "input": None, "error_type": "ValidationError"},
        {"id": "invalid-array", "input": [], "error_type": "ValidationError"},
    ]
    ledger = BudgetLedger(args.output / "billing")
    ledger.create("real-plan-build", dollars=0, tokens=100000, requests=2)
    backend = ResponsesBackend(
        config,
        LocalTransport(args.local_endpoint, approved=True),
        ledger=ledger,
        account="real-plan-build",
    )
    result = {
        "actual_model_planning": False,
        "actual_model_generation": False,
        "paid_api_calls": 0,
        "independent_cases": len(cases),
    }
    try:
        spec = backend.plan(goal, "ascii-digit-count", "python-json")
        result["actual_model_planning"] = True
        write_json(args.output / "plan.json", spec)
        if spec["inputs"].get("type") != "string":
            raise ValueError("Model plan did not preserve the stated string root")
        if (
            spec["outputs"].get("type") != "object"
            or spec["outputs"].get("properties", {}).get("count", {}).get("type") != "integer"
        ):
            raise ValueError("Model plan did not infer the requested count result")
        generator = ModelGenerator(backend)
        skill = generator.generate(spec, args.output / "skills/ascii-digit-count")
        result["actual_model_generation"] = True
        write_json(args.output / "model.bundle.json", generator.last_bundle, safe=True)
        report = evaluate_batches(
            skill, spec, cases, args.output / "planning", read_json(args.runtime_config), timeout=45
        )
        write_json(args.output / "report.json", report, safe=True)
        result.update(
            status=report["status"],
            metrics=report["metrics"],
            artifact_hash=report["artifact_hash"],
            model_contract_summary=generator.last_contract_summary,
        )
    except Exception as exc:
        result.update(status="failed", error=str(exc))
    finally:
        backend.save_receipts(args.output / "receipts.json")
        result["persistent_budget"] = ledger.status("real-plan-build")
        write_json(args.output / "summary.json", result, safe=True)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
