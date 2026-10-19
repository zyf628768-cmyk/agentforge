"""Run and record v0.2 offline engineering acceptance; never provision or call a model."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agentforge.core import read_json, tree_hash, write_json


def verify(output: Path):
    if output.exists():
        raise RuntimeError("Preserve prior evidence; choose a new output directory")
    output.mkdir(parents=True)
    output = output.resolve()
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "examples/v02"
    records = []

    def run(command, expected=0):
        command = [str(v) for v in command]
        started = time.monotonic()
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=180,
        )
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "expected_exit_code": expected,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "seconds": time.monotonic() - started,
            }
        )
        write_json(output / "commands.json", records, safe=True)
        assert result.returncode == expected, records[-1]
        print(f"OK exit={result.returncode}: " + " ".join(command[:5]), flush=True)
        return result.stdout

    def cli(*args, expected=0):
        return json.loads(
            run(
                [sys.executable, "-m", "agentforge", "--home", output / "registry", *args], expected
            )
        )

    run([sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(output / "junit.xml")])
    run([sys.executable, "-m", "ruff", "check", "src", "tests", "tools"])
    run([sys.executable, "tools/probe_limits.py", "--output", output / "os-limits.json"])
    doctor = cli("doctor")
    spec = read_json(fixtures / "integer-stats.plan.json")
    planned = output / "planned.json"
    cli(
        "plan",
        spec["goal"],
        "--name",
        spec["name"],
        "--kind",
        "wasm-json",
        "--response",
        fixtures / "integer-stats.planning-response.json",
        "--output",
        planned,
        "--model-receipts",
        output / "planning-receipts.json",
    )
    clean = output / "clean/integer-stats"
    cli(
        "build",
        planned,
        "--response",
        fixtures / "integer-stats.response.json",
        "--output",
        clean,
        "--model-receipts",
        output / "build-receipts.json",
    )
    evaluation = fixtures / "integer-stats.evaluation.json"
    report = cli(
        "test", clean, "--evaluation", evaluation, "--report", output / "integer-stats-test.json"
    )
    numeric = cli("run", clean, "--input", clean / "examples/input.json")
    assert numeric == {"sum": 6, "count": 3}
    assert cli("test", clean, expected=2)["status"] == "unverified"
    cli("registry", "add", clean, "--evaluation", evaluation, "--activate")
    broken = output / "broken/integer-stats"
    cli(
        "build",
        planned,
        "--bundle",
        fixtures / "integer-stats.broken.bundle.json",
        "--output",
        broken,
    )
    before_hash = tree_hash(broken)
    before = cli(
        "test", broken, "--evaluation", evaluation, "--report", output / "before.json", expected=2
    )
    repaired = cli(
        "evolve",
        broken,
        "--output",
        output / "repair",
        "--evaluation",
        evaluation,
        "--response",
        fixtures / "integer-stats.response.json",
        "--model-receipts",
        output / "repair-receipts.json",
    )
    assert repaired["accepted"] and tree_hash(broken) == before_hash
    candidate = Path(repaired["attempts"][0]["path"])
    comparison = cli(
        "compare",
        broken,
        candidate,
        "--evaluation",
        evaluation,
        "--report",
        output / "comparison.json",
    )
    active_before = cli("registry", "show", "integer-stats")
    regression = cli(
        "evolve",
        candidate,
        "--mode",
        "optimize",
        "--output",
        output / "regression",
        "--evaluation",
        evaluation,
        "--bundle",
        fixtures / "integer-stats.broken.bundle.json",
        expected=2,
    )
    active_after = cli("registry", "show", "integer-stats")
    assert not regression["accepted"] and active_before["hash"] == active_after["hash"]
    rot13 = output / "rot13"
    cli(
        "build",
        fixtures / "rot13.plan.json",
        "--response",
        fixtures / "rot13.response.json",
        "--output",
        rot13,
        "--model-receipts",
        output / "rot13-receipts.json",
    )
    cli(
        "test",
        rot13,
        "--evaluation",
        fixtures / "rot13.evaluation.json",
        "--report",
        output / "rot13-test.json",
    )
    transformed = cli("run", rot13, "--input", rot13 / "examples/input.json")
    assert transformed == "Uryyb 世界!"
    python = output / "csv-summary"
    cli(
        "build",
        fixtures / "csv-summary.plan.json",
        "--response",
        fixtures / "csv-summary.response.json",
        "--output",
        python,
        "--model-receipts",
        output / "csv-receipts.json",
    )
    python_report = cli(
        "test",
        python,
        "--evaluation",
        fixtures / "csv-summary.evaluation.json",
        "--report",
        output / "python-blocked.json",
        expected=2,
    )
    assert python_report["status"] == "blocked" and python_report["checks"]["passed"]
    write_json(
        output / "live-config-review-only.json",
        {
            "model": "not-selected",
            "max_cost_usd": 0.01,
            "input_usd_per_million": 1,
            "output_usd_per_million": 1,
        },
    )
    gate = cli(
        "build",
        planned,
        "--model-config",
        output / "live-config-review-only.json",
        "--model-receipts",
        output / "no-live-receipts.json",
        "--output",
        output / "live-not-called/integer-stats",
        expected=2,
    )
    assert gate["status"] == "refused" and not (output / "no-live-receipts.json").exists()
    summary = {
        "status": "passed",
        "version": "0.2.0a1",
        "commands": len(records),
        "live_model_requests": 0,
        "credentials_inspected": False,
        "model_tests": "authored offline protocol fixtures; live HTTP path mocked in tests",
        "numeric_output": numeric,
        "rot13_output": transformed,
        "before": before["metrics"],
        "after": report["metrics"],
        "comparison": comparison,
        "regression_rejected": True,
        "stable_hash_retained": active_after["hash"],
        "os_limits": doctor["probe"]["os_limits"],
        "python_runtime": "blocked; actual rootless gVisor environment not available/provisioned",
        "docker_binary_present": bool(shutil.which("docker")),
        "production_ready": False,
        "remaining": [
            "approved real-model quality/cost acceptance",
            "real Linux/gVisor hostile-code integration and cleanup/reaper qualification",
            "cross-platform CI execution",
            "independent security review and deployment operations",
        ],
    }
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().output), ensure_ascii=True, indent=2))
