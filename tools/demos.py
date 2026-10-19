"""Three real CLI demonstrations. Assertions fail if evidence contradicts claims."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agentforge.core import read_json, tree_hash, write_json


def demonstrations(output: Path) -> dict:
    if output.exists():
        raise RuntimeError("Choose a new demonstration output directory")
    output.mkdir(parents=True)
    output = output.resolve()
    home = output / "registry"
    commands = []

    def run(*args, expected=0):
        command = [sys.executable, "-m", "agentforge", "--home", str(home), *(str(a) for a in args)]
        started = time.monotonic()
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=60,
            check=False,
        )
        record = {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "seconds": time.monotonic() - started,
            "expected_exit_code": expected,
        }
        commands.append(record)
        write_json(output / "commands.json", commands, safe=True)
        assert proc.returncode == expected, record
        return json.loads(proc.stdout)

    run("doctor")
    spec_path = output / "plan.json"
    run("plan", "清洗文本空白并保留大小写", "--output", spec_path)
    clean = output / "clean" / "text-cleaner"
    run("build", spec_path, "--output", clean)
    clean_report = run("test", clean, "--report", output / "demo1-test.json")
    actual = run("run", clean, "--input", clean / "examples/input.json")
    assert actual == {"text": "Hello 世界"}
    stable_hash = tree_hash(clean)
    run("registry", "add", clean, "--activate")
    write_json(
        output / "demo1.json",
        {
            "status": "passed",
            "output": actual,
            "hash": stable_hash,
            "tests": clean_report["metrics"],
        },
    )

    spec = read_json(spec_path)
    spec["version"] = "0.2.0"
    bug_plan = output / "bug-plan.json"
    write_json(bug_plan, spec)
    broken = output / "broken" / "text-cleaner"
    run("build", bug_plan, "--output", broken, "--variant", "bug")
    before = run("test", broken, "--report", output / "demo2-before.json", expected=2)
    broken_hash = tree_hash(broken)
    repaired = run(
        "evolve",
        broken,
        "--output",
        output / "repair",
        "--max-iterations",
        2,
        "--seconds",
        30,
        "--cost-usd",
        0,
    )
    assert repaired["accepted"]
    candidate = Path(repaired["attempts"][0]["path"])
    after = run("test", candidate, "--report", output / "demo2-after.json")
    comparison = run("compare", broken, candidate, "--report", output / "comparison.json")
    assert comparison["accepted"] and tree_hash(broken) == broken_hash
    write_json(
        output / "demo2.json",
        {
            "status": "passed",
            "before": before["metrics"],
            "after": after["metrics"],
            "repair": repaired,
            "baseline_preserved": tree_hash(broken) == broken_hash,
        },
    )

    active_before = run("registry", "show", "text-cleaner")
    rejected = run(
        "evolve", candidate, "--mode", "regression", "--output", output / "regression", expected=2
    )
    active_after = run("registry", "show", "text-cleaner")
    assert not rejected["accepted"]
    assert active_after["hash"] == active_before["hash"]
    assert tree_hash(clean) == stable_hash
    run("registry", "rollback", "text-cleaner", "--version", "0.1.0")
    export = output / "rollback-export" / "text-cleaner"
    run("registry", "export", "text-cleaner", "--output", export)
    assert tree_hash(export) == stable_hash
    write_json(
        output / "demo3.json",
        {
            "status": "passed",
            "upgrade_rejected": True,
            "retained_version": active_after["version"],
            "retained_hash": active_after["hash"],
            "candidate": rejected,
            "rollback_hash": tree_hash(export),
        },
    )
    run("registry", "list")
    summary = {
        "status": "passed",
        "demos": 3,
        "real_commands": len(commands),
        "demo1": "WASM text cleaner executed with expected Unicode output",
        "demo2": "TAB defect reproduced, separate repair passed fresh tests",
        "demo3": "Case-changing regression rejected, active hash retained",
        "comparison": comparison,
        "final_active": "0.1.0",
    }
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(demonstrations(parser.parse_args().output), ensure_ascii=True, indent=2))
