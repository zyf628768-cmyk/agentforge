"""Explicitly selected CPython/WASI runtime, without native Python guest execution."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from .core import ForgeError, files, redact, strict_json
from .process_limits import ResourceContainmentError, bounded_worker
from .sandbox import SandboxUnavailable, worker_environment


class PythonWasi:
    def __init__(self, *, runtime_dir: str | Path, manifest_sha256: str, timeout: float = 15):
        if not 0 < timeout <= 30:
            raise ForgeError("WASI Python time budget must be finite and at most 30 seconds")
        self.runtime_dir = Path(runtime_dir).absolute()
        self.manifest_sha256 = manifest_sha256
        self.timeout = timeout

    def preflight(self) -> dict:
        if not re.fullmatch(r"[a-f0-9]{64}", self.manifest_sha256):
            raise SandboxUnavailable("An explicitly approved runtime manifest SHA-256 is required")
        for parent in [self.runtime_dir, *self.runtime_dir.parents]:
            if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                raise SandboxUnavailable("Runtime paths cannot use links or junctions")
            if (parent / "manifest.json").is_file():
                raise SandboxUnavailable("Runtime must be outside untrusted Skill artifacts")
        manifest = self.runtime_dir / "runtime-manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise SandboxUnavailable("Approved CPython/WASI runtime is not installed locally")
        raw = manifest.read_bytes()
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise SandboxUnavailable("Runtime manifest differs from the approved hash")
        value = strict_json(raw)
        hashes = value.get("files", {})
        if not isinstance(hashes, dict) or not 2 <= len(hashes) <= 5000:
            raise SandboxUnavailable("Runtime file manifest is invalid")
        total = 0
        for name, expected in hashes.items():
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in name
                or ":" in name
                or not re.fullmatch(r"[a-f0-9]{64}", expected)
            ):
                raise SandboxUnavailable("Unsafe runtime manifest path or hash")
            path = self.runtime_dir.joinpath(*relative.parts)
            if not path.is_file() or path.is_symlink():
                raise SandboxUnavailable("Runtime files must be regular and match their manifest")
            total += path.stat().st_size
            if total > 128 * 1024 * 1024:
                raise SandboxUnavailable("Runtime exceeds the size limit")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise SandboxUnavailable("Runtime file integrity/size check failed")
        # Refuse extra files and linked directories, not only entries named in the manifest.
        actual = set()
        for path in self.runtime_dir.rglob("*"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise SandboxUnavailable("Runtime directory contains a link/junction")
            if path.is_file():
                actual.add(path.relative_to(self.runtime_dir).as_posix())
        if actual != set(hashes) | {"runtime-manifest.json"} or "python.wasm" not in hashes:
            raise SandboxUnavailable("Runtime directory differs from the sealed file set")
        return {
            "backend": "cpython-wasi",
            "manifest_sha256": self.manifest_sha256,
            "guest_memory_limit_bytes": 64 * 1024 * 1024,
            "fuel_per_case": 5_000_000_000,
            "readonly_preopens": ["/runtime", "/skill"],
            "network": False,
            "host_environment_inherited": False,
            "native_guest_processes": False,
        }

    def execute(self, root: Path, inputs: list, spec: dict) -> dict:
        policy = self.preflight()
        if len(inputs) > 128:
            raise ForgeError("WASI Python request exceeds the case limit")
        sources = {
            p.relative_to(root).as_posix(): base64.b64encode(p.read_bytes()).decode()
            for p in files(root)
            if p.relative_to(root).parts[0] == "scripts"
        }
        payload = json.dumps(
            {
                "runtime_dir": str(self.runtime_dir),
                "manifest_sha256": self.manifest_sha256,
                "sources": sources,
                "inputs": inputs,
                "spec": spec,
                "timeout": self.timeout,
            }
        )
        if len(payload.encode()) > 5_000_000:
            raise ForgeError("WASI Python request exceeds the byte limit")
        command = [sys.executable, "-I", "-m", "agentforge._wasi_worker"]
        try:
            with tempfile.TemporaryDirectory(prefix="agentforge-wasi-worker-") as tmp:
                result, limits = bounded_worker(
                    command,
                    payload,
                    env=worker_environment(),
                    cwd=tmp,
                    timeout=self.timeout,
                    memory_bytes=512 * 1024 * 1024,
                )
        except (OSError, subprocess.TimeoutExpired, ResourceContainmentError) as exc:
            return {
                "status": "blocked",
                "results": [],
                "command": command,
                "exit_code": None,
                "error": type(exc).__name__,
                "isolation": policy,
            }
        evidence = {
            "command": command,
            "exit_code": result.returncode,
            "stderr": redact(result.stderr[:4000]),
            "os_limits": limits,
            "isolation": policy,
        }
        try:
            if result.returncode or len(result.stdout) > 4_000_000:
                raise ValueError("WASI worker failed")
            report = strict_json(result.stdout)
            if not isinstance(report, dict) or not isinstance(report.get("results"), list):
                raise ValueError("Invalid worker response")
        except (ValueError, TypeError):
            return {
                **evidence,
                "status": "blocked",
                "results": [],
                "error": "Contained WASI worker failed",
            }
        return {**evidence, **report}


def python_runtime(config: dict | None, *, timeout: float = 15):
    """Select only the explicitly requested backend; never weaken or fall back."""
    value = dict(config or {})
    if value.get("backend") == "python-wasi":
        if set(value) != {"backend", "runtime_dir", "manifest_sha256"}:
            raise ForgeError(
                "WASI policy requires exactly backend, runtime_dir and manifest_sha256"
            )
        value.pop("backend")
        return PythonWasi(timeout=timeout, **value)
    if "backend" in value:
        raise ForgeError("Unknown explicit Python isolation backend")
    from .containers import PythonContainer

    return PythonContainer(timeout=timeout, **value)
