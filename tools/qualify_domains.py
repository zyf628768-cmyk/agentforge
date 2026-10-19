"""Run independent multi-domain acceptance in WASI or actual local model generation."""

import argparse
import json
import time
from pathlib import Path

from domain_cases import domains

from agentforge.artifacts import BundleGenerator
from agentforge.billing import BudgetLedger
from agentforge.contracts import contract_hash
from agentforge.core import read_json, write_json
from agentforge.evolution import Budget, evolve
from agentforge.local_model import LocalTransport
from agentforge.providers import ModelConfig, ModelGenerator, ResponsesBackend
from agentforge.registry import Registry
from agentforge.spec import general_plan
from agentforge.testing import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-endpoint")
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--approve-local-model", action="store_true")
    parser.add_argument("--repair-iterations", type=int, choices=range(3), default=0)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument(
        "--domain", action="append", help="Explicit subset for a separately recorded trial"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")
    if args.local_endpoint and (not args.approve_local_model or not args.model_config):
        parser.error("Real local generation requires --model-config and --approve-local-model")
    if not 30 <= args.seconds <= 3600:
        parser.error("Phase wall budget must be 30..3600 seconds")
    if args.repair_iterations and not args.local_endpoint:
        parser.error("Controlled repair qualification requires actual local inference")
    args.output.mkdir(parents=True)
    deadline = time.monotonic() + args.seconds
    selected = domains()
    if args.domain:
        if not set(args.domain) <= {domain["name"] for domain in selected}:
            parser.error("Unknown qualification domain")
        selected = [domain for domain in selected if domain["name"] in args.domain]
    config = read_json(args.runtime_config)
    records = {
        "fixture_generation": not bool(args.local_endpoint),
        "paid_api_calls": 0,
        "domains": [],
        "scope": {
            "domain_count": len(selected),
            "positive_independent_cases": sum(len(d["cases"]) for d in selected),
            "negative_independent_cases": 2 * len(selected),
            "repair_iterations": args.repair_iterations,
            "wall_seconds": args.seconds,
            "public_reproducible_cases": True,
        },
    }
    if args.local_endpoint:
        model = ModelConfig(**read_json(args.model_config))
        if model.max_requests < 1 + args.repair_iterations:
            parser.error("Model request budget must include initial generation and allowed repairs")
        if model.max_cost_usd or model.input_usd_per_million or model.output_usd_per_million:
            parser.error("Local inference must use zero monetary rates")
        ledger = BudgetLedger(args.output / "billing")
        ledger.create(
            "qualification",
            dollars=0,
            tokens=1000000,
            requests=len(selected) * (1 + args.repair_iterations),
        )
    registry = Registry(args.output / "registry") if args.repair_iterations else None
    for domain in selected:
        name = domain["name"]
        start = time.monotonic()
        spec = general_plan(
            domain["goal"], name, "python-json", inputs=domain["inputs"], outputs=domain["outputs"]
        )
        evaluation = args.output / (name + ".independent.json")
        write_json(
            evaluation,
            {
                "contract_hash": contract_hash(spec),
                "cases": [
                    {"id": f"independent-{i}", "input": value, "expected": expected}
                    for i, (value, expected) in enumerate(domain["cases"])
                ]
                + [
                    {
                        "id": "independent-invalid-null",
                        "input": None,
                        "error_type": "ValidationError",
                    },
                    {
                        "id": "independent-invalid-root",
                        "input": {} if domain["inputs"]["type"] == "array" else [],
                        "error_type": "ValidationError",
                    },
                ],
            },
        )
        backend = None
        if args.local_endpoint:
            backend = ResponsesBackend(
                model,
                LocalTransport(args.local_endpoint, approved=True),
                ledger=ledger,
                account="qualification",
            )
            backend.deadline = deadline
            generator = ModelGenerator(backend)
        else:
            value, expected = domain["cases"][0]
            generator = BundleGenerator(
                {
                    "files": [
                        {"path": "scripts/main.py", "content": domain["source"]},
                        {
                            "path": "README.md",
                            "content": "# "
                            + name
                            + "\nAuthored deterministic fixture, not model output.",
                        },
                        {
                            "path": "tests/cases.json",
                            "content": json.dumps(
                                [{"id": "generated-example", "input": value, "expected": expected}]
                            ),
                        },
                        {"path": "examples/input.json", "content": json.dumps(value)},
                        {"path": "examples/output.json", "content": json.dumps(expected)},
                    ]
                }
            )
        result = {"name": name}
        try:
            artifact = generator.generate(spec, args.output / "skills" / name)
            if getattr(generator, "last_contract_summary", None):
                result["model_contract_summary"] = generator.last_contract_summary
            if getattr(generator, "last_bundle", None):
                write_json(
                    args.output / (name + ".initial-model-bundle.json"),
                    generator.last_bundle,
                    safe=True,
                )
            report = evaluate(
                artifact,
                args.output / (name + ".report.json"),
                timeout=30,
                evaluation_path=evaluation,
                container_config=config,
            )
            result.update(status=report["status"], metrics=report["metrics"])
            result["initial_status"] = report["status"]
            if report["status"] == "failed" and args.repair_iterations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Qualification phase wall budget exhausted")
                repair = evolve(
                    artifact,
                    args.output / "repairs" / name,
                    registry,
                    generator=generator,
                    evaluation_path=evaluation,
                    container_config=config,
                    budget=Budget(args.repair_iterations, min(600, remaining), 0),
                )
                result["repair"] = repair
                if repair["accepted"]:
                    candidate = Path(repair["attempts"][-1]["path"])
                    final_report = candidate.parent / "evaluation.json"
                    verified = read_json(final_report)
                    result.update(
                        status=verified["status"],
                        metrics=verified["metrics"],
                        accepted_artifact=str(candidate),
                        report=str(final_report),
                    )
        except Exception as exc:
            result.update(status="failed", error=str(exc)[:2000])
        finally:
            if getattr(generator, "last_bundle", None):
                write_json(
                    args.output / (name + ".model-bundle.json"), generator.last_bundle, safe=True
                )
            if backend:
                backend.save_receipts(args.output / (name + ".receipts.json"))
            result["seconds"] = time.monotonic() - start
            records["domains"].append(result)
            write_json(args.output / "summary.json", records, safe=True)
            print(name, result["status"], flush=True)
    records["status"] = (
        "passed" if all(d["status"] == "passed" for d in records["domains"]) else "failed"
    )
    if args.local_endpoint:
        records["persistent_budget"] = ledger.status("qualification")
    write_json(args.output / "summary.json", records, safe=True)
    if records["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
