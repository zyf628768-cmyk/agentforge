"""Controlled repair/evolution. Candidates are never written over the baseline."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .core import ForgeError, read_json, write_json
from .generator import Generator, OfflineGenerator
from .registry import Registry
from .testing import compare, evaluate


@dataclass(frozen=True)
class Budget:
    max_iterations: int = 2
    seconds: float = 30
    cost_usd: float = 0

    def __post_init__(self):
        if (
            not math.isfinite(self.cost_usd)
            or not 0 <= self.max_iterations <= 20
            or not 0 < self.seconds <= 600
            or self.cost_usd < 0
        ):
            raise ForgeError("Budget: 0..20 iterations, 0 < seconds <= 600, cost >= 0")


def classify(report: dict) -> dict:
    if report["status"] == "blocked":
        return {
            "category": "safety-or-environment",
            "reproducers": report["checks"]["errors"],
            "execution_error": (report.get("execution") or {}).get("error"),
        }
    failures = [c for c in report["cases"] if not c["passed"]]
    return {
        "category": "functional" if failures else "none",
        "reproducers": [
            {"id": c["id"], "input": c["input"], "expected": c["expected"], "actual": c["actual"]}
            for c in failures
        ],
    }


def evolve(
    root: Path,
    destination: Path,
    registry: Registry,
    *,
    mode: str = "repair",
    budget: Budget | None = None,
    generator: Generator | None = None,
    evaluation_path: Path | None = None,
    container_config: dict | None = None,
) -> dict:
    budget = budget or Budget()
    if mode not in {"repair", "regression", "optimize"}:
        raise ForgeError("Evolution mode must be repair, optimize or regression")
    if destination.exists():
        raise ForgeError("Evolution output exists; choose a new output directory")
    if destination.resolve().is_relative_to(root.resolve()):
        raise ForgeError("Evolution evidence and candidates must be outside the baseline Skill")
    destination.mkdir(parents=True)
    started = time.monotonic()
    backend = getattr(generator, "backend", None)
    if backend:
        if not backend.transport.offline and (
            budget.cost_usd <= 0 or backend.config.max_cost_usd > budget.cost_usd
        ):
            raise ForgeError("Model spend cap must fit within the explicit evolution cost budget")
        backend.deadline = started + budget.seconds
    baseline = evaluate(
        root,
        destination / "baseline.json",
        timeout=min(5.0, budget.seconds),
        evaluation_path=evaluation_path,
        container_config=container_config,
    )
    result = {
        "baseline_hash": baseline["artifact_hash"],
        "baseline_status": baseline["status"],
        "classification": classify(baseline),
        "attempts": [],
        "accepted": False,
        "budget": budget.__dict__,
        "cost_usd": 0,
        "stop_reason": "iteration-budget",
    }
    manifest = read_json(root / "manifest.json")
    last_report = baseline
    if baseline["status"] in {"blocked", "unverified"}:
        result["stop_reason"] = (
            "independent-evaluation-required"
            if baseline["status"] == "unverified"
            else "safety-blocked"
        )
    elif mode == "repair" and baseline["status"] == "passed":
        result["stop_reason"] = "already-passing"
    else:
        for iteration in range(budget.max_iterations):
            if time.monotonic() - started >= budget.seconds:
                result["stop_reason"] = "time-budget"
                break
            # Only a reproducible TAB defect has a supported offline repair.
            generic = manifest["kind"] != "text-cleaner"
            if generic and generator is None:
                raise ForgeError("Generic repair/evolution requires an artifact or model generator")
            if (
                not generic
                and mode == "repair"
                and not any(c["id"] == "unit-tab" and not c["passed"] for c in baseline["cases"])
            ):
                result["stop_reason"] = "no-supported-repair"
                break
            spec = read_json(root / "spec.json")
            major, minor, patch = map(int, spec["version"].split("."))
            occupied = {
                r["version"] for r in registry.list(spec["name"]) if r["name"] == spec["name"]
            }
            candidate_patch = patch + iteration + 1
            while f"{major}.{minor}.{candidate_patch}" in occupied:
                candidate_patch += 1
            spec["version"] = f"{major}.{minor}.{candidate_patch}"
            candidate = destination / ("candidate-" + uuid.uuid4().hex[:8]) / spec["name"]
            if generic:
                if hasattr(generator, "feedback"):
                    feedback_report = last_report
                    generator.feedback = [
                        c
                        for c in feedback_report["cases"]
                        if not c["passed"] and c["suite"] in {"unit", "integration"}
                    ]
                try:
                    generator.generate(spec, candidate)
                except ForgeError as exc:
                    result["attempts"].append(
                        {"iteration": iteration + 1, "generation_error": str(exc)}
                    )
                    result["stop_reason"] = "generation-refused"
                    break
            else:
                OfflineGenerator().generate(
                    spec, candidate, "regression" if mode == "regression" else "correct"
                )
            remaining = budget.seconds - (time.monotonic() - started)
            if remaining <= 0:
                result["stop_reason"] = "time-budget"
                break
            report = evaluate(
                candidate,
                candidate.parent / "evaluation.json",
                timeout=min(5.0, remaining),
                regression_cases=baseline["cases"],
                evaluation_path=evaluation_path,
                container_config=container_config,
            )
            comparison = compare(baseline, report)
            last_report = report
            active = next(
                (
                    r
                    for r in registry.list(manifest["name"])
                    if r["name"] == manifest["name"] and r["active"]
                ),
                None,
            )
            if active:
                stable_comparison = compare(
                    registry.show(active["name"], active["version"])["report"], report
                )
                if not stable_comparison["accepted"]:
                    comparison["accepted"] = False
                    comparison["reasons"].extend(
                        "Active stable version: " + r for r in stable_comparison["reasons"]
                    )
            if time.monotonic() - started >= budget.seconds:
                comparison["accepted"] = False
                comparison["reasons"].append("Time budget exhausted; promotion prohibited")
                result["stop_reason"] = "time-budget"
            row = registry.register(candidate, report)
            if time.monotonic() - started >= budget.seconds:
                comparison["accepted"] = False
                comparison["reasons"].append("Deadline exhausted during snapshot registration")
                result["stop_reason"] = "time-budget"
            attempt = {
                "iteration": iteration + 1,
                "path": str(candidate.resolve()),
                "version": row["version"],
                "comparison": comparison,
                "classification": classify(report),
            }
            result["attempts"].append(attempt)
            if comparison["accepted"]:
                # Explicit evolve is authorization to update a local active pointer only.
                try:
                    registry.activate(
                        manifest["name"],
                        row["version"],
                        rollback=True,
                        expected_active=active["version"] if active else None,
                    )
                except ForgeError as exc:
                    comparison["accepted"] = False
                    comparison["reasons"].append(str(exc))
                    result["stop_reason"] = "activation-refused"
                    break
                result["accepted"] = True
                result["stop_reason"] = "validated-candidate"
                break
            result["stop_reason"] = (
                "candidate-rejected" if result["stop_reason"] != "time-budget" else "time-budget"
            )
            # Deterministic backend has no other candidate; repeated retries add no evidence.
            if not backend or result["stop_reason"] == "time-budget":
                break
    result["seconds"] = time.monotonic() - started
    if backend:
        result["cost_usd"] = sum(float(r["cost_usd"]) for r in backend.receipts)
    result["baseline_preserved"] = True
    write_json(destination / "evolution.json", result, safe=True)
    return result
