"""Small, complete JSON-output command-line interface."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sqlite3
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
    command.add_argument(
        "--local-model", help="Explicit loopback llama.cpp chat endpoint; no paid API"
    )
    command.add_argument(
        "--approve-local-model", action="store_true", help="Authorize free local inference"
    )
    command.add_argument(
        "--budget-account", help="Previously initialized persistent budget account"
    )
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
    local_endpoint = getattr(args, "local_model", None)
    ledger = None
    if local_endpoint:
        from .local_model import LocalTransport

        if args.response or args.approve_model_request or args.credential_env:
            raise ForgeError("Select local inference without fixture or paid credential options")
        if not args.model_config or not getattr(args, "approve_local_model", False):
            raise ForgeError(
                "Local inference requires explicit model config and --approve-local-model"
            )
        if config.max_cost_usd or config.input_usd_per_million or config.output_usd_per_million:
            raise ForgeError("Free local inference requires zero monetary rates and cap")
        transport = LocalTransport(local_endpoint, approved=True)
    elif args.response:
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
        # Defer the selected credential read until the durable account is validated too.
        transport = None
    account = getattr(args, "budget_account", None)
    if transport is None or not transport.offline:
        from .billing import BudgetLedger

        if not account:
            raise ForgeError("Real inference requires an initialized --budget-account")
        ledger = BudgetLedger(args.home / "billing")
        ledger.status(account)  # Validate before handing the backend any requests.
    if transport is None:
        transport = OpenAITransport(os.environ.get(args.credential_env, ""), approved=True)
    return ResponsesBackend(config, transport, ledger=ledger, account=account)


def container_arguments(command):
    command.add_argument("--evaluation", type=Path, help="Independent evaluator-owned JSON cases")
    command.add_argument(
        "--container-config",
        "--python-runtime-config",
        type=Path,
        help="Explicit Python isolation policy: rootless gVisor or sealed CPython/WASI",
    )


def container_config(args):
    if not getattr(args, "container_config", None):
        return None
    config = read_json(args.container_config)
    valid = isinstance(config, dict) and (
        set(config) == {"image", "socket", "lease_dir"}
        or (
            set(config) == {"backend", "runtime_dir", "manifest_sha256"}
            and config["backend"] == "python-wasi"
        )
    )
    if not valid:
        raise ForgeError("Invalid explicit Python runtime policy")
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
    billing = commands.add_parser(
        "budget", help="Durable shared inference budgets and explicit reconciliation"
    )
    billing_actions = billing.add_subparsers(dest="action", required=True)
    create = billing_actions.add_parser(
        "create", help="Initialize immutable lifetime limits for an account"
    )
    create.add_argument("account")
    create.add_argument("--usd", type=str, required=True)
    create.add_argument("--tokens", type=int, required=True)
    create.add_argument("--requests", type=int, required=True)
    status = billing_actions.add_parser(
        "status", help="Show charged/held budget and unresolved reservations"
    )
    status.add_argument("account")
    history = billing_actions.add_parser(
        "history", help="List up to 1000 durable reservation records"
    )
    history.add_argument("account")
    reconcile = billing_actions.add_parser(
        "reconcile", help="Record operator-reviewed actual usage for an unresolved call"
    )
    reconcile.add_argument("reservation")
    reconcile.add_argument("--usd", required=True)
    reconcile.add_argument("--tokens", type=int, required=True)
    reconcile.add_argument("--receipt", type=Path, required=True)
    reconcile.add_argument("--note", required=True)
    init = commands.add_parser("init", help="Initialize local registry and editable example plan")
    init.add_argument("path", type=Path, nargs="?", default=Path("."))
    planning = commands.add_parser("plan", help="Plan editable generic Skill contracts")
    planning.add_argument("goal")
    planning.add_argument("--name", default="text-cleaner")
    planning.add_argument("--output", type=Path, required=True)
    planning.add_argument(
        "--kind", choices=["text-cleaner", "wasm-json", "python-json"], default="text-cleaner"
    )
    planning.add_argument("--contract", type=Path, help="Human-editable input/output schemas")
    planning.add_argument(
        "--review-plan",
        action="store_true",
        help="One bounded free-local-model self-review; requires request/token budget",
    )
    model_arguments(planning)
    build = commands.add_parser(
        "build", help="Generate executable WASM, scripts, schemas and tests"
    )
    build.add_argument("spec", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--variant", choices=["correct", "bug", "regression"], default="correct")
    build.add_argument("--bundle", type=Path, help="Provider-neutral executable file bundle")
    build.add_argument(
        "--example-input",
        type=Path,
        action="append",
        help="Operator-reviewed JSON input only; at most three, never evaluator cases",
    )
    model_arguments(build)
    test = commands.add_parser(
        "test", help="Inspect and execute independent Skill tests in the selected sandbox"
    )
    test.add_argument("skill", type=Path)
    test.add_argument("--report", type=Path)
    container_arguments(test)
    run = commands.add_parser("run", help="Run the Skill JSON entrypoint in isolation")
    run.add_argument("skill", type=Path)
    run.add_argument("--input", type=Path, help="JSON file; default stdin")
    run.add_argument("--container-config", "--python-runtime-config", type=Path)
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
    evolution.add_argument(
        "--example-input",
        type=Path,
        action="append",
        help="Operator-reviewed JSON input only; at most three, never evaluator cases",
    )
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
    doctor = commands.add_parser(
        "doctor", help="Probe runtime, actual WASM execution, and local tools"
    )
    doctor.add_argument("--container-config", "--python-runtime-config", type=Path)
    sandbox = commands.add_parser("sandbox", help="Supervise durable Python container leases")
    sandbox_actions = sandbox.add_subparsers(dest="action", required=True)
    for name in ("supervise", "status", "reap"):
        action = sandbox_actions.add_parser(
            name,
            help={
                "supervise": "Run the independent crash-recovery supervisor",
                "status": "Check the daemon, supervisor heartbeat and outstanding leases",
                "reap": "Retry expired and interrupted container cleanup once",
            }[name],
        )
        action.add_argument("--container-config", type=Path, required=True)
        if name == "supervise":
            action.add_argument("--once", action="store_true")
    return cli


def dispatch(args: argparse.Namespace) -> tuple[object, int]:
    command = args.command
    if command == "budget":
        from .billing import BudgetLedger

        ledger = BudgetLedger(args.home / "billing")
        if args.action == "create":
            return ledger.create(
                args.account, dollars=args.usd, tokens=args.tokens, requests=args.requests
            ), 0
        if args.action == "status":
            return ledger.status(args.account), 0
        if args.action == "history":
            return ledger.history(args.account), 0
        if (
            not args.receipt.is_file()
            or args.receipt.is_symlink()
            or args.receipt.stat().st_size > 1_000_000
        ):
            raise ForgeError("Require a bounded regular provider receipt")
        return ledger.reconcile(
            args.reservation,
            amount=args.usd,
            tokens=args.tokens,
            receipt=args.receipt.read_bytes(),
            note=redact(args.note),
        ), 0
    if command == "sandbox":
        from .containers import PythonContainer

        config = container_config(args)
        if config.get("backend"):
            raise ForgeError("Container supervisor commands require a gVisor lease policy")
        runtime = PythonContainer(**config)
        if args.action == "supervise":
            return runtime.supervise(once=args.once), 0
        policy = runtime.preflight()
        if args.action == "reap":
            result = runtime.sweep()
            return result, 2 if result["failed"] else 0
        store = runtime.lease_store()
        return {
            "policy": policy,
            "supervisor": store.require_reaper(),
            "outstanding": store.outstanding(),
        }, 0
    if command == "init":
        target = args.path / "agentforge-plan.json"
        if target.exists():
            raise ForgeError("Plan exists; refusing to overwrite")
        registry = Registry(args.path / ".agentforge")
        write_json(target, plan("Clean text whitespace"))
        return {"plan": str(target.resolve()), "registry": str(registry.db)}, 0
    if command == "plan":
        if args.review_plan and not args.local_model:
            raise ForgeError("--review-plan requires an explicitly selected free local model")
        if args.output.exists():
            raise ForgeError("Output already exists")
        if args.response or args.model_config or args.local_model:
            if args.kind == "text-cleaner":
                raise ForgeError("Model planning requires a generic JSON target")
            backend = model_backend(args)
            try:
                spec = backend.plan(
                    args.goal,
                    args.name,
                    args.kind,
                    contract=read_json(args.contract) if args.contract else None,
                    review=args.review_plan,
                )
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
        if args.example_input and not (args.response or args.model_config or args.local_model):
            raise ForgeError("Example inputs require an explicitly selected model generator")
        spec = read_json(args.spec)
        if args.output.name != spec.get("name"):
            raise ForgeError("Output directory must match the Skill name")
        if args.bundle and (args.response or args.model_config or args.local_model):
            raise ForgeError("Select one artifact source")
        backend = None
        if args.bundle:
            from .artifacts import BundleGenerator

            generator = BundleGenerator.from_file(args.bundle)
        elif args.response or args.model_config or args.local_model:
            from .providers import ModelGenerator

            backend = model_backend(args)
            generator = ModelGenerator(
                backend, example_inputs=[read_json(p) for p in args.example_input or []]
            )
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
        if args.example_input and not (args.response or args.model_config or args.local_model):
            raise ForgeError("Example inputs require an explicitly selected model generator")
        backend = None
        generator = None
        if args.bundle and (args.response or args.model_config or args.local_model):
            raise ForgeError("Select one candidate source")
        if args.bundle:
            from .artifacts import BundleGenerator

            generator = BundleGenerator.from_file(args.bundle)
        elif args.response or args.model_config or args.local_model:
            from .providers import ModelGenerator

            backend = model_backend(args)
            generator = ModelGenerator(
                backend, example_inputs=[read_json(p) for p in args.example_input or []]
            )
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
            "production_qualified": False,
            "durable_model_budgets": "SQLite per explicit operator home/account",
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
        if args.container_config:
            from .python_wasi import python_runtime

            runtime = python_runtime(container_config(args))
            status["python_runtime"] = runtime.preflight()
            if hasattr(runtime, "lease_store"):
                status["python_runtime"]["supervisor"] = runtime.lease_store().require_reaper()
        return status, 0 if status["ready"] else 2
    raise ForgeError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result, code = dispatch(args)
    except (
        ForgeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        sqlite3.Error,
    ) as exc:
        result, code = {"error": str(exc), "status": "refused"}, 2
    print(json.dumps(redact(result), ensure_ascii=True, indent=2))
    return code
