"""Verify a native platform wheelhouse in a new venv without index/network fallback."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.venv.exists():
        parser.error("Evidence and venv paths must be new")
    args.output.mkdir(parents=True)
    venv.create(args.venv, with_pip=True)
    python = args.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    records = []

    def run(command):
        command = list(map(str, command))
        started = time.monotonic()
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
        )
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "seconds": time.monotonic() - started,
            }
        )
        (args.output / "commands.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Offline verification failed; see real commands.json")

    wheels = list(args.wheelhouse.glob("agentforge-*-py3-none-any.whl"))
    if len(wheels) != 1:
        parser.error("Require exactly one AgentForge wheel")
    run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            args.wheelhouse,
            str(wheels[0]) + "[dev]",
        ]
    )
    run([python, "-m", "pip", "check"])
    for name in [
        "init",
        "plan",
        "build",
        "test",
        "run",
        "evolve",
        "compare",
        "registry",
        "doctor",
        "sandbox",
        "budget",
    ]:
        run([python, "-m", "agentforge", name, "--help"])
    run([python, "-m", "agentforge", "doctor"])
    run([python, "-m", "pytest", "-q", "--junitxml=" + str(args.output / "junit.xml")])
    run([python, "tools/demos.py", "--output", args.output / "demos"])
    (args.output / "environment.json").write_text(
        json.dumps(
            {
                "python": sys.version,
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "offline_install": True,
                "status": "passed",
                "wheel": wheels[0].name,
            },
            indent=2,
        )
    )
    print("Fresh offline installation passed:", platform.platform(), flush=True)


if __name__ == "__main__":
    main()
