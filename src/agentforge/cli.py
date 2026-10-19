"""Small, complete JSON-output command-line interface."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

from . import __version__
from .core import ForgeError, read_json, redact, strict_json, write_json
from .evolution import Budget, evolve
from .generator import OfflineGenerator
from .registry import Registry
from .sandbox import Sandbox, run_skill
from .spec import general_plan, plan
from .testing import compare, evaluate


def model_arguments(command):
    command.add_argument("--model-config", type=Path, help="Explicit model, token and spend limits")
    command.add_argument(
        "--response", type=Path, help="Offline Responses protocol fixture; no network"
    )
    command.add_argument(
        "--model-receipts", type=Path, help="Required audit output for any model backend"
    )
    command.add_argument(
        "--approve-model-request",
        action="store_true",
        help="Explicit authorization for a live request",
    )
    command.add_argument(
        "--credential-env", help="Explicit credential variable; never auto-discovered"
    )


def model_backend(args):
    from .providers import ModelConfig, OpenAITransport, RecordedTransport, ResponsesBackend

    if not args.model_receipts:
        raise ForgeError("Model backend requires --model-receipts audit output")
    if (
        args.model_receipts.exists()
        or args.model_receipts.is_symlink()
        or any(
            (parent / "manifest.json").is_file() for parent in args.model_receipts.resolve().parents
        )
    ):
        raise ForgeError("Model audit output must be new and outside immutable Skill artifacts")
    config = (
        ModelConfig(**read_json(args.model_config))
        if args.model_config
        else ModelConfig(model="offline-fixture")
    )
    if args.response:
        if args.approve_model_request or args.credential_env:
            raise ForgeError("Offline fixture mode does not accept live credential options")
        value = read_json(args.response)
        if not isinstance(value, dict) or not isinstance(value.get("responses"), list):
            raise ForgeError("Offline fixture requires a responses array")
        transport = RecordedTransport(value["responses"])
    else:
        if not args.model_config or not args.approve_model_request or not args.credential_env:
            raise ForgeError(
                "Live model requests require explicit config, approval and a selected credential variable"
            )
        if (
            config.max_cost_usd <= 0
            or min(config.input_usd_per_million, config.output_usd_per_million) <= 0
        ):
            raise ForgeError("Review positive pricing and spend cap before selecting a credential")
        import os
        import re

        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", args.credential_env):
            raise ForgeError("Invalid explicit credential variable")
        # This single selected read is reachable only after all explicit live gates.
        transport = OpenAITransport(os.environ.get(args.credential_env, ""), approved=True)
    return ResponsesBackend(config, transport)


def container_arguments(command):
    command.add_argument("--evaluation", type=Path, help="Independent evaluator-owned JSON cases")
    command.add_argument(
        "--container-config",
        type=Path,
        help="Approved local rootless socket and immutable image digest",
    )


def container_config(args):
    if not getattr(args, "container_config", None):
        return None
    config = read_json(args.container_config)
    if not isinstance(config, dict) or set(config) != {"image", "socket"}:
        raise ForgeError("Container policy must contain exactly image and local socket")
    return config


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="agentforge", description="Offline, isolated Skill engineering"
    )
    cli.add_argument("--version", action="version", version=__version__)
    cli.add_argument(
        "--home", type=Path, default=Path(".agentforge"), help="Local SQLite/Git registry"
    )
    commands = cli.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize local registry and editable example plan")
    init.add_argument("path", type=Path, nargs="?", default=Path("."))
    planning = commands.add_parser(
        "plan", help="Plan text-cleaning capabilities; JSON is human-editable"
    )
    planning.add_argument("goal")
    planning.add_argument("--name", default="text-cleaner")
    planning.add_argument("--output", type=Path, required=True)
    planning.add_argument(
        "--kind", choices=["text-cleaner", "wasm-json", "python-json"], default="text-cleaner"
    )
    planning.add_argument("--contract", type=Path, help="Human-editable input/output schemas")
    model_arguments(planning)
    build = commands.add_parser(
        "build", help="Generate executable WASM, scripts, schemas and tests"
    )
    build.add_argument("spec", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--variant", choices=["correct", "bug", "regression"], default="correct")
    build.add_argument("--bundle", type=Path, help="Provider-neutral executable file bundle")
    model_arguments(build)
    test = commands.add_parser(
        "test", help="Statically inspect and execute WASM tests in isolation"
    )
    test.add_argument("skill", type=Path)
    test.add_argument("--report", type=Path)
    container_arguments(test)
    run = commands.add_parser("run", help="Run the WASM entrypoint on JSON input")
    run.add_argument("skill", type=Path)
    run.add_argument("--input", type=Path, help="JSON file; default stdin")
    run.add_argument("--container-config", type=Path)
    evolution = commands.add_parser(
        "evolve", help="Evaluate isolated repair or evolution candidates"
    )
    evolution.add_argument("skill", type=Path)
    evolution.add_argument("--output", type=Path, required=True)
    evolution.add_argument("--mode", choices=["repair", "optimize", "regression"], default="repair")
    evolution.add_argument("--max-iterations", type=int, default=2)
    evolution.add_argument("--seconds", type=float, default=30)
    evolution.add_argument("--cost-usd", type=float, default=0)
    evolution.add_argument("--bundle", type=Path, help="Controlled generic repair candidate")
    model_arguments(evolution)
    container_arguments(evolution)
    comparison = commands.add_parser(
        "compare", help="Compare two fresh independent Skill evaluations"
    )
    comparison.add_argument("baseline", type=Path)
    comparison.add_argument("candidate", type=Path)
    comparison.add_argument("--report", type=Path)
    container_arguments(comparison)
    registry = commands.add_parser(
        "registry", help="Search, inspect, register, export or roll back snapshots"
    )
    actions = registry.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="Search by Skill name")
    listing.add_argument("query", nargs="?", default="")
    add = actions.add_parser("add", help="Fresh evaluation then immutable registration")
    add.add_argument("skill", type=Path)
    add.add_argument("--activate", action="store_true")
    container_arguments(add)
    for action in ("show", "export", "rollback"):
        sub = actions.add_parser(
            action,
            help={
                "show": "Read version metadata and evidence",
                "export": "Export Git snapshot into a new directory",
                "rollback": "Restore active pointer to a verified Git snapshot",
            }[action],
        )
        sub.add_argument("name")
        sub.add_argument("--version", required=action == "rollback")
        if action == "export":
            sub.add_argument("--output", type=Path, required=True)
    commands.add_parser("doctor", help="Probe runtime, actual WASM execution, and local tools")
    return cli


def dispatch(args: argparse.Namespace) -> tuple[object, int]:
    command = args.command
    if command == "init":
        target = args.path / "agentforge-plan.json"
        if target.exists():
            raise ForgeError("Plan exists; refusing to overwrite")
        registry = Registry(args.path / ".agentforge")
        write_json(target, plan("Clean text whitespace"))
        return {"plan": str(target.resolve()), "registry": str(registry.db)}, 0
    if command == "plan":
        if args.output.exists():
            raise ForgeError("Output already exists")
        if args.response or args.model_config:
            if args.kind == "text-cleaner":
                raise ForgeError("Model planning requires a generic JSON target")
            backend = model_backend(args)
            try:
                spec = backend.plan(args.goal, args.name, args.kind)
            finally:
                backend.save_receipts(args.model_receipts)
        elif args.kind == "text-cleaner":
            spec = plan(args.goal, args.name)
        else:
            contract = read_json(args.contract) if args.contract else {}
            spec = general_plan(args.goal, args.name, args.kind, **contract)
        write_json(args.output, spec)
        return spec, 0
    if command == "build":
        spec = read_json(args.spec)
        if args.output.name != spec.get("name"):
            raise ForgeError("Output directory must match the Skill name")
        if args.bundle and (args.response or args.model_config):
            raise ForgeError("Select one artifact source")
        backend = None
        if args.bundle:
            from .artifacts import BundleGenerator

            generator = BundleGenerator.from_file(args.bundle)
        elif args.response or args.model_config:
            from .providers import ModelGenerator

            backend = model_backend(args)
            generator = ModelGenerator(backend)
        else:
            generator = OfflineGenerator()
        try:
            path = generator.generate(spec, args.output, args.variant)
        finally:
            if backend:
                backend.save_receipts(args.model_receipts)
        return {"path": str(path.resolve()), "backend": type(generator).__name__}, 0
    if command == "test":
        report = evaluate(
            args.skill,
            args.report,
            evaluation_path=args.evaluation,
            container_config=container_config(args),
        )
        return report, 0 if report["status"] == "passed" else 2
    if command == "run":
        value = read_json(args.input) if args.input else strict_json(sys.stdin.read(100_001))
        evidence = run_skill(args.skill, value, container_config=container_config(args))
        return evidence["results"][0]["output"], 0
    if command == "evolve":
        backend = None
        generator = None
        if args.bundle and (args.response or args.model_config):
            raise ForgeError("Select one candidate source")
        if args.bundle:
            from .artifacts import BundleGenerator

            generator = BundleGenerator.from_file(args.bundle)
        elif args.response or args.model_config:
            from .providers import ModelGenerator

            backend = model_backend(args)
            generator = ModelGenerator(backend)
        try:
            result = evolve(
                args.skill,
                args.output,
                Registry(args.home),
                mode=args.mode,
                budget=Budget(args.max_iterations, args.seconds, args.cost_usd),
                generator=generator,
                evaluation_path=args.evaluation,
                container_config=container_config(args),
            )
        finally:
            if backend:
                backend.save_receipts(args.model_receipts)
        return result, 0 if result["accepted"] or result["stop_reason"] == "already-passing" else 2
    if command == "compare":
        baseline = evaluate(
            args.baseline, evaluation_path=args.evaluation, container_config=container_config(args)
        )
        result = compare(
            baseline,
            evaluate(
                args.candidate,
                regression_cases=baseline["cases"],
                evaluation_path=args.evaluation,
                container_config=container_config(args),
            ),
        )
        if args.report:
            write_json(args.report, result, safe=True)
        return result, 0 if result["accepted"] else 2
    if command == "registry":
        registry = Registry(args.home)
        if args.action == "list":
            return registry.list(args.query), 0
        if args.action == "show":
            return registry.show(args.name, args.version), 0
        if args.action == "add":
            report = evaluate(
                args.skill, evaluation_path=args.evaluation, container_config=container_config(args)
            )
            row = registry.register(args.skill, report)
            if args.activate:
                registry.activate(row["name"], row["version"])
            return row, 0 if report["status"] == "passed" else 2
        if args.action == "rollback":
            return registry.activate(args.name, args.version, rollback=True), 0
        return {"exported": str(registry.export(args.name, args.version, args.output).resolve())}, 0
    if command == "doctor":
        status = {
            "python": platform.python_version(),
            "agentforge": __version__,
            "git": bool(shutil.which("git")),
            "wasmtime": Sandbox.available(),
            "backend": "wasmtime-no-imports",
            "host_python_execution": False,
            "model_backend": "openai-responses-with-explicit-live-gate",
            "live_model_requests_default": False,
            "python_container_requires": "local rootless Docker + cgroup v2 + seccomp + runsc + approved digest",
        }
        if status["wasmtime"]:
            import wasmtime

            wasm = bytes(
                wasmtime.wat2wasm(
                    '(module (memory (export "memory") 1 1) (func (export "clean") (param i32) (result i32) i32.const 0))'
                )
            )
            status["probe"] = Sandbox().execute(wasm, [{"text": ""}])
            status["ready"] = (
                status["probe"]["status"] == "completed"
                and status["probe"]["results"][0]["ok"]
                and status["git"]
            )
        else:
            status["ready"] = False
            status["reason"] = "Sandbox missing; untrusted execution refused"
        return status, 0 if status["ready"] else 2
    raise ForgeError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result, code = dispatch(args)
    except (ForgeError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        result, code = {"error": str(exc), "status": "refused"}, 2
    print(json.dumps(redact(result), ensure_ascii=True, indent=2))
    return code
