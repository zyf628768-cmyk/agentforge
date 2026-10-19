"""Build distributions, gather free wheels and verify an offline fresh installation.

Run from an editable development install. This does not publish or push anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

from agentforge.core import write_json
from agentforge.generator import OfflineGenerator
from agentforge.spec import plan


def prepare(root: Path, attempt: str) -> None:
    if not attempt or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in attempt):
        raise ValueError("Attempt must use lowercase ASCII letters, digits and hyphens")
    evidence = root / "outputs/evidence" / attempt
    if evidence.exists():
        raise RuntimeError("Evidence directory exists; use a new --attempt")
    evidence.mkdir(parents=True, exist_ok=True)
    records = []

    def run(command, expected=0, timeout=180):
        started = time.monotonic()
        proc = subprocess.run(
            [str(a) for a in command],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        record = {
            "command": [str(a) for a in command],
            "exit_code": proc.returncode,
            "expected_exit_code": expected,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "seconds": time.monotonic() - started,
        }
        records.append(record)
        write_json(evidence / "fresh-install.json", records, safe=True)
        if proc.returncode != expected:
            raise RuntimeError(json.dumps(record, ensure_ascii=True))
        print(f"OK exit={proc.returncode}: " + " ".join(str(a) for a in command), flush=True)
        return proc

    spec = plan("Clean text whitespace")
    write_json(root / "examples/text-cleaner.plan.json", spec)
    example = root / "examples/text-cleaner"
    if not example.exists():
        OfflineGenerator().generate(spec, example)
    schema = root / "schemas/spec.schema.json"
    schema.parent.mkdir(exist_ok=True)
    schema.write_bytes((root / "src/agentforge/data/spec.schema.json").read_bytes())
    locks = sorted(
        f"{dist.metadata['Name']}=={dist.version}"
        for dist in metadata.distributions()
        if dist.metadata["Name"].lower() not in {"pip", "agentforge"}
    )
    lock = root / "requirements-lock.txt"
    lock.write_text(
        "# Verified Windows x64 / CPython 3.12 development and runtime dependencies\n"
        + "\n".join(locks)
        + "\n",
        encoding="utf-8",
    )
    run([sys.executable, "-m", "build", "--outdir", root / "outputs/dist"])
    wheelhouse = root / "outputs/wheelhouse"
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--dest",
            wheelhouse,
            "-r",
            lock,
        ]
    )
    fresh = root / "work" / ("fresh-" + attempt)
    if fresh.exists():
        raise RuntimeError(
            "Fresh environment already exists; preserve evidence and choose a new workspace"
        )
    run([sys.executable, "-m", "venv", fresh])
    fresh_python = fresh / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    wheel = root / "outputs/dist/agentforge-0.1.0-py3-none-any.whl"
    run(
        [
            fresh_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            wheelhouse,
            "-r",
            lock,
            wheel,
        ]
    )
    run([fresh_python, "-m", "pip", "check"])
    run([fresh_python, "-m", "agentforge", "doctor"])
    run([fresh_python, "tools/acceptance.py", "--output", evidence / "acceptance"])
    run([fresh_python, "tools/demos.py", "--output", evidence / "demos"])
    # Probe actual runtime absence in this disposable fresh environment, then restore it.
    run([fresh_python, "-m", "pip", "uninstall", "-y", "wasmtime"])
    doctor_missing = run([fresh_python, "-m", "agentforge", "doctor"], expected=2)
    missing = run(
        [
            fresh_python,
            "-m",
            "agentforge",
            "test",
            example,
            "--report",
            evidence / "sandbox-unavailable.json",
        ],
        expected=2,
    )
    assert not json.loads(doctor_missing.stdout)["ready"]
    assert json.loads(missing.stdout)["status"] == "blocked"
    assert json.loads(missing.stdout)["execution"] is None
    run(
        [
            fresh_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            wheelhouse,
            next(item for item in locks if item.lower().startswith("wasmtime==")),
        ]
    )
    run([fresh_python, "-m", "agentforge", "doctor"])
    write_json(
        evidence / "environment.json",
        {
            "python": sys.version,
            "platform": sys.platform,
            "fresh_python": str(fresh_python),
            "offline_install": True,
            "dependency_lock": locks,
            "wheel": str(wheel),
            "scope": "Local Windows x64 Python 3.12 verified; CI matrix configured, not run here",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", default="v0.1.0")
    prepare(Path(__file__).resolve().parents[1], parser.parse_args().attempt)
