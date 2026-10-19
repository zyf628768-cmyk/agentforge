"""Record real acceptance commands and map them to the requested eighteen checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agentforge.core import write_json


def acceptance(output: Path) -> dict:
    if output.exists():
        raise RuntimeError("Choose a new acceptance output directory")
    output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    records = []
    commands = [
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml=" + str((output / "junit.xml").resolve()),
        ],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "tools"],
        [sys.executable, "-m", "agentforge", "doctor"],
    ]
    for command in commands:
        started = time.monotonic()
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            cwd=root,
            timeout=180,
            check=False,
        )
        records.append(
            {
                "command": command,
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "seconds": time.monotonic() - started,
            }
        )
        write_json(output / "commands.json", records, safe=True)
    passed = all(record["exit_code"] == 0 for record in records)
    checks = [
        (1, "Fresh wheel installation", "See fresh-install.json; separate new venv installation"),
        (2, "All CLI entrypoints", "test_all_cli_help; demos command log"),
        (3, "Editable specification parsing", "test_spec_parsing_editing_and_schema"),
        (4, "Complete project generation", "test_project_and_generator_protocol"),
        (5, "SKILL.md specification checks", "test_skill_spec_integrity_and_dependency_checks"),
        (6, "Generator interface", "test_project_and_generator_protocol"),
        (7, "Real engine execution", "test_real_engine_execution_and_evidence"),
        (8, "Failure identification", "test_failure_identification_and_controlled_repair"),
        (9, "Repair candidate generation", "test_failure_identification_and_controlled_repair"),
        (10, "Retesting repair", "test_failure_identification_and_controlled_repair"),
        (
            11,
            "Version comparison",
            "test_regression_rejected_and_stable_retained; demos/comparison.json",
        ),
        (
            12,
            "Failed improvement retains old version",
            "test_regression_rejected_and_stable_retained",
        ),
        (
            13,
            "SQLite version registration and reading",
            "test_registry_sqlite_git_export_and_rollback",
        ),
        (14, "Git snapshots and rollback", "test_registry_sqlite_git_export_and_rollback"),
        (15, "Budgets and iteration limits", "test_loop_and_time_limits; test_budget_invalid"),
        (
            16,
            "Sensitive information filtering",
            "test_sensitive_information_filtering_and_rejection",
        ),
        (17, "Sandbox unavailable refusal", "test_sandbox_unavailable_refuses_without_process"),
        (18, "Real executable Skill end to end", "demos/commands.json; demo1.json"),
    ]
    result = {
        "suite_passed": passed,
        "checks": [
            {"id": number, "requirement": title, "evidence": evidence}
            for number, title, evidence in checks
        ],
        "note": "Mapping is not a substituted result; inspect real commands, JUnit, fresh install and demos.",
    }
    write_json(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = acceptance(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["suite_passed"] else 1)
