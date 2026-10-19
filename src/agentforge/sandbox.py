"""No-import WebAssembly capability sandbox, with an external wall-clock watchdog.

The subprocess is a trusted worker, NOT the isolation boundary. Wasmtime's
validated linear memory and lack of imports are the boundary for guest code.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from .core import ForgeError, redact
from .process_limits import ResourceContainmentError, bounded_worker


class SandboxUnavailable(ForgeError):
    pass


def worker_environment() -> dict[str, str]:
    """Only OS bootstrap data, derived architecture and no inherited credentials."""
    if os.name != "nt":
        return {"AGENTFORGE_PARENT_PID": str(os.getpid())}
    # Python 3.11 platform.machine() reads this variable on Windows. Wasmtime uses
    # that API to select its native library. Derive the value from the Python build
    # rather than inheriting arbitrary host metadata or the host environment.
    architectures = {"win-amd64": "AMD64", "win-arm64": "ARM64", "win32": "x86"}
    architecture = architectures.get(sysconfig.get_platform())
    if architecture is None:
        raise SandboxUnavailable("Unsupported Windows Python architecture")
    return {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "PROCESSOR_ARCHITECTURE": architecture,
    }


class Sandbox:
    def __init__(self, *, fuel: int = 2_000_000, timeout: float = 5.0):
        if not 1 <= fuel <= 20_000_000 or not 0 < timeout <= 30:
            raise ForgeError("Sandbox limits outside permitted bounds")
        self.fuel = fuel
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("wasmtime") is not None

    def execute(
        self,
        wasm: bytes,
        inputs: list[dict],
        *,
        contract: dict | None = None,
        wat: str | None = None,
    ) -> dict:
        if not self.available():
            raise SandboxUnavailable("Wasmtime unavailable; untrusted execution refused")
        if len(wasm) > 100_000 or len(inputs) > 128:
            raise ForgeError("Execution request exceeds bounded WASM/case limits")
        payload = json.dumps(
            {
                "wasm": base64.b64encode(wasm).decode(),
                "inputs": inputs,
                "fuel": self.fuel,
                "contract": contract,
                "wat": wat,
                "cpu_seconds": self.timeout,
            }
        )
        if len(payload) > 250_000:
            raise ForgeError("Execution input exceeds size limit")
        command = [sys.executable, "-I", "-m", "agentforge._worker"]
        # No inherited keys, Python paths, proxy settings or credentials.
        env = worker_environment()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="agentforge-worker-") as tmp:
            try:
                proc, os_limits = bounded_worker(
                    command, payload, env=env, cwd=tmp, timeout=self.timeout
                )
            except (subprocess.TimeoutExpired, OSError, ResourceContainmentError) as exc:
                return {
                    "command": command,
                    "exit_code": getattr(exc, "returncode", None),
                    "status": "blocked",
                    "error": type(exc).__name__,
                    "wall_seconds": time.monotonic() - started,
                    "results": [],
                    "isolation": "wasmtime-no-imports",
                }
        evidence = {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": redact(proc.stdout[:100_000]),
            "stderr": redact(proc.stderr[:4000]),
            "wall_seconds": time.monotonic() - started,
            "isolation": "wasmtime-no-imports",
            "os_limits": os_limits,
            "limits": {
                "fuel_per_case": self.fuel,
                "memory_bytes": 65536,
                "timeout_seconds": self.timeout,
                "imports": [],
                "filesystem": False,
                "network": False,
                "environment": False,
            },
        }
        try:
            result = json.loads(proc.stdout)
            if proc.returncode != 0 or not isinstance(result.get("results"), list):
                raise ValueError("worker failed")
        except (ValueError, AttributeError):
            return {
                **evidence,
                "status": "blocked",
                "error": "Trusted worker failed",
                "results": [],
            }
        return {**evidence, **result}

    def compile(self, wat: str) -> bytes:
        """Untrusted model WAT is compiled only in the resource-contained worker."""
        result = self.execute(b"", [], wat=wat)
        if result["status"] != "completed" or "compiled_wasm" not in result:
            raise ForgeError(
                "Contained WAT compilation refused: " + str(result.get("error", "worker failure"))
            )
        binary = base64.b64decode(result["compiled_wasm"], validate=True)
        if len(binary) > 100_000:
            raise ForgeError("Compiled WASM exceeds module limit")
        return binary


def run_skill(root: Path, value: dict, *, container_config: dict | None = None) -> dict:
    from .validation import inspect_skill

    checks = inspect_skill(root)
    if not checks["passed"]:
        raise ForgeError("Skill validation failed: " + "; ".join(checks["errors"]))
    from .core import read_json

    spec = read_json(root / "spec.json")
    manifest = read_json(root / "manifest.json")
    if spec["kind"] == "python-json":
        from .python_wasi import python_runtime

        result = python_runtime(container_config).execute(root, [value], spec)
    else:
        result = Sandbox().execute(
            (root / manifest["entrypoint"]).read_bytes(),
            [value],
            contract=spec if spec["kind"] != "text-cleaner" else None,
        )
    if result["status"] != "completed" or not result["results"][0].get("ok"):
        raise ForgeError("Sandbox execution failed: " + json.dumps(result))
    return result
