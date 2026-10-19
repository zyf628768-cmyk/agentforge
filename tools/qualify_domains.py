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
from agentforge.local_model import LocalTransport
from agentforge.providers import ModelConfig, ModelGenerator, ResponsesBackend
from agentforge.spec import general_plan
from agentforge.testing import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-endpoint")
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--approve-local-model", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")
    if args.local_endpoint and (not args.approve_local_model or not args.model_config):
        parser.error("Real local generation requires --model-config and --approve-local-model")
    args.output.mkdir(parents=True)
    config = read_json(args.runtime_config)
    records = {
        "fixture_generation": not bool(args.local_endpoint),
        "paid_api_calls": 0,
        "domains": [],
    }
    if args.local_endpoint:
        model = ModelConfig(**read_json(args.model_config))
        if model.max_cost_usd or model.input_usd_per_million or model.output_usd_per_million:
            parser.error("Local inference must use zero monetary rates")
        ledger = BudgetLedger(args.output / "billing")
        ledger.create("qualification", dollars=0, tokens=1000000, requests=10)
    for domain in domains():
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
            report = evaluate(
                artifact,
                args.output / (name + ".report.json"),
                timeout=30,
                evaluation_path=evaluation,
                container_config=config,
            )
            result.update(status=report["status"], metrics=report["metrics"])
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
    write_json(args.output / "summary.json", records, safe=True)
    if records["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
