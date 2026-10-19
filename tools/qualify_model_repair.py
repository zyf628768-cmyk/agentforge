"""Inject a documented fault into real model source, repair it, reject regression."""

import argparse
import ast
import copy
import hashlib
from pathlib import Path

from agentforge.artifacts import BundleGenerator
from agentforge.billing import BudgetLedger
from agentforge.core import read_json, write_json
from agentforge.evolution import Budget, evolve
from agentforge.local_model import LocalTransport
from agentforge.providers import ModelConfig, ModelGenerator, ResponsesBackend
from agentforge.registry import Registry
from agentforge.validation import inspect_skill


def inject_fault(bundle):
    candidate = copy.deepcopy(bundle)
    source = next(f for f in candidate["files"] if f["path"] == "scripts/main.py")
    tree = ast.parse(source["content"])
    operators = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
    ]
    if len(operators) != 1:
        raise ValueError("This controlled invoice experiment requires exactly one multiplication")
    operators[0].op = ast.Add()
    source["content"] = ast.unparse(tree) + "\n"
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--local-endpoint", required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--approve-local-model", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve existing experimental evidence")
    inspected = inspect_skill(args.baseline)
    if not inspected["passed"]:
        parser.error("Baseline integrity/static checks failed: " + str(inspected["errors"]))
    manifest = read_json(args.baseline / "manifest.json")
    if not manifest["source"].startswith("local-llama.cpp:"):
        parser.error("Require actual local model source as the experiment's baseline")
    model = ModelConfig(**read_json(args.model_config))
    if model.max_cost_usd or model.input_usd_per_million or model.output_usd_per_million:
        parser.error("Only explicitly approved free local inference is supported here")
    args.output.mkdir(parents=True)
    names = [
        "scripts/main.py",
        "README.md",
        "tests/cases.json",
        "examples/input.json",
        "examples/output.json",
    ]
    original = {
        "files": [
            {"path": name, "content": (args.baseline / name).read_text(encoding="utf-8")}
            for name in names
        ]
    }
    mutated = inject_fault(original)
    write_json(args.output / "fault-injected.bundle.json", mutated, safe=True)
    spec = read_json(args.baseline / "spec.json")
    broken = BundleGenerator(mutated, source="controlled-fault-in-real-model-source").generate(
        spec, args.output / "broken" / spec["name"]
    )
    ledger = BudgetLedger(args.output / "billing")
    ledger.create("actual-model-repair", dollars=0, tokens=200000, requests=2)
    backend = ResponsesBackend(
        model,
        LocalTransport(args.local_endpoint, approved=True),
        ledger=ledger,
        account="actual-model-repair",
    )
    generator = ModelGenerator(backend)
    registry = Registry(args.output / "registry")
    config = read_json(args.runtime_config)
    result = {
        "actual_model_inference": True,
        "paid_api_calls": 0,
        "fault": "Replace the single multiplication AST operator with addition; never execute source on host",
        "original_source_sha256": hashlib.sha256(
            (args.baseline / "scripts/main.py").read_bytes()
        ).hexdigest(),
    }
    try:
        repaired = evolve(
            broken,
            args.output / "repair",
            registry,
            generator=generator,
            evaluation_path=args.evaluation,
            container_config=config,
            budget=Budget(2, 600, 0),
        )
        result["repair"] = repaired
        if not repaired["accepted"]:
            raise RuntimeError("Real-model repair did not pass independent acceptance")
        candidate = Path(repaired["attempts"][-1]["path"])
        active_before = registry.show(spec["name"])
        regression = evolve(
            candidate,
            args.output / "regression",
            registry,
            mode="optimize",
            generator=BundleGenerator(mutated, source="authored-adversarial-regression"),
            evaluation_path=args.evaluation,
            container_config=config,
            budget=Budget(1, 90, 0),
        )
        active_after = registry.show(spec["name"])
        result["regression"] = regression
        result["active_before"] = active_before["hash"]
        result["active_after"] = active_after["hash"]
        assert not regression["accepted"] and active_before["hash"] == active_after["hash"]
        result["status"] = "passed"
    except Exception as exc:
        result.update(status="failed", error=str(exc))
    finally:
        backend.save_receipts(args.output / "model-receipts.json")
        if generator.last_bundle:
            write_json(args.output / "model-repair.bundle.json", generator.last_bundle, safe=True)
        result["persistent_budget"] = ledger.status("actual-model-repair")
        write_json(args.output / "summary.json", result, safe=True)
    print(result["status"], flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
