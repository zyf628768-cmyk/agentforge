"""Actual OS quota probe using an authored trusted helper, never generated Python."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentforge.core import write_json
from agentforge.process_limits import bounded_worker


def probe(output):
    if os.name != "nt":
        result = {"status": "not-run", "reason": "This physical quota probe targets Windows Jobs"}
    else:
        with tempfile.TemporaryDirectory(prefix="agentforge-quota-probe-") as tmp:
            script = Path(tmp) / "trusted_probe.py"
            script.write_text(
                "import sys\nsys.stdin.read()\ntry:\n    x=bytearray(128*1024*1024)\n    print('quota-escaped')\nexcept MemoryError:\n    print('allocation-denied')\n",
                encoding="utf-8",
            )
            command = [sys.executable, "-I", str(script)]
            completed, policy = bounded_worker(
                command,
                "start",
                env={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
                cwd=tmp,
                timeout=3,
                memory_bytes=64 * 1024 * 1024,
            )
            assert completed.returncode == 0 and completed.stdout.strip() == "allocation-denied"
            memory = {
                "command": command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "actual_limits": policy,
            }
            script.write_text(
                "import sys\nsys.stdin.read()\nwhile True:\n    pass\n", encoding="utf-8"
            )
            started = time.monotonic()
            try:
                bounded_worker(
                    command,
                    "start",
                    env={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
                    cwd=tmp,
                    timeout=0.3,
                )
            except subprocess.TimeoutExpired:
                wall = {
                    "status": "terminated",
                    "timeout_seconds": 0.3,
                    "actual_seconds": time.monotonic() - started,
                }
            else:
                raise AssertionError("Watchdog did not terminate the probe")
            result = {
                "status": "passed",
                "memory_probe": memory,
                "process_tree_watchdog": wall,
                "scope": "OS resource containment; not an arbitrary Python sandbox",
            }
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(probe(parser.parse_args().output), indent=2))
