"""Record independent automated scanner results; never label them a human audit."""

import argparse
import importlib.metadata
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence directory must be new")
    args.output.mkdir(parents=True)
    # Runtime transitive dependencies only; audit does not transmit project data or credentials.
    names = [
        "wasmtime",
        "jsonschema",
        "PyYAML",
        "attrs",
        "jsonschema-specifications",
        "referencing",
        "rpds-py",
        "typing-extensions",
    ]
    lock = args.output / "runtime-lock.txt"
    lock.write_text(
        "\n".join(name + "==" + importlib.metadata.version(name) for name in names) + "\n"
    )
    records = []
    commands = [
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--disable-pip",
            "--no-deps",
            "-r",
            str(lock),
            "-f",
            "json",
            "-o",
            str(args.output / "dependency-audit.json"),
        ],
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "src/agentforge",
            "-f",
            "json",
            "-o",
            str(args.output / "bandit.json"),
        ],
    ]
    for command in commands:
        start = time.monotonic()
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180
        )
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "seconds": time.monotonic() - start,
            }
        )
        (args.output / "commands.json").write_text(json.dumps(records, indent=2))
        print("Scanner exit", result.returncode, command[2], flush=True)
    print("Automated scanner evidence recorded; findings require triage, not suppression.")


if __name__ == "__main__":
    main()
