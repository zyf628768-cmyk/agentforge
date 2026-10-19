"""Fail-closed Python JSON execution in explicitly provisioned rootless gVisor.

Docker/venv/subprocess alone is never accepted as a Python code sandbox. Images
must already exist locally under an approved immutable digest. No pulls/builds,
package installation, privileged containers or writable host mounts are performed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .core import ForgeError, files, redact, strict_json
from .sandbox import SandboxUnavailable


def capped_attach(command: list[str], data: str, timeout: float) -> tuple[int, str, str]:
    config = tempfile.TemporaryDirectory(prefix="agentforge-docker-config-")
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": os.defpath, "HOME": config.name, "DOCKER_CONFIG": config.name},
    )
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def reader(stream, target):
        try:
            while chunk := stream.read(4096):
                remaining = 65536 - len(target)
                target.extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    overflow.set()
                    process.kill()
                    break
        except (OSError, ValueError):
            pass

    def writer():
        try:
            process.stdin.write(data.encode())
            process.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [
        threading.Thread(target=reader, args=(process.stdout, buffers[0]), daemon=True),
        threading.Thread(target=reader, args=(process.stderr, buffers[1]), daemon=True),
        threading.Thread(target=writer, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for thread in threads:
            thread.join(timeout=1)
        config.cleanup()
    if overflow.is_set():
        raise ForgeError("Container output exceeded 64 KiB stream limit")
    return process.returncode, *(b.decode("utf-8", errors="replace") for b in buffers)


class PythonContainer:
    def __init__(
        self,
        *,
        image: str | None = None,
        socket: str | None = None,
        timeout: float = 5,
        control=None,
        attach=None,
    ):
        self.image, self.socket, self.timeout = image, socket, timeout
        self.control = control or self._control
        self.attach = attach or capped_attach
        self.commands = []

    @staticmethod
    def _control(command):
        try:
            with tempfile.TemporaryDirectory(prefix="agentforge-docker-config-") as tmp:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    env={"PATH": os.defpath, "HOME": tmp, "DOCKER_CONFIG": tmp},
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailable(
                "Container control unavailable; host Python execution refused"
            ) from exc
        if result.returncode:
            raise SandboxUnavailable("Container control failed; no fallback execution")
        return result.stdout

    def _call(self, *args):
        command = ["docker", "--host", self.socket, *args]
        self.commands.append(command)
        return self.control(command)

    def preflight(self) -> dict:
        if not self.image or not re.fullmatch(
            r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", self.image
        ):
            raise SandboxUnavailable(
                "Python execution requires an explicitly approved local image digest"
            )
        if not self.socket or not re.fullmatch(
            r"unix:///run/user/[0-9]+/docker\.sock", self.socket
        ):
            raise SandboxUnavailable(
                "Only an explicitly selected local rootless Unix socket is permitted"
            )
        info = json.loads(self._call("info", "--format", "{{json .}}"))
        options = " ".join(info.get("SecurityOptions", []))
        if (
            info.get("OSType") != "linux"
            or info.get("CgroupVersion") != "2"
            or not info.get("CgroupDriver")
            or info["CgroupDriver"] == "none"
            or "rootless" not in options
            or "seccomp" not in options
            or "runsc" not in info.get("Runtimes", {})
            or info.get("Warnings")
        ):
            raise SandboxUnavailable(
                "Require rootless Linux Docker, cgroup v2 resource control, seccomp and runsc without warnings"
            )
        image = json.loads(self._call("image", "inspect", self.image))
        if (
            not isinstance(image, list)
            or len(image) != 1
            or self.image not in image[0].get("RepoDigests", [])
        ):
            raise SandboxUnavailable(
                "Approved immutable image is not installed locally; no pull is permitted"
            )
        allowed = {
            "PATH",
            "LANG",
            "LC_ALL",
            "PYTHON_VERSION",
            "PYTHON_SHA256",
            "PYTHON_PIP_VERSION",
            "PYTHON_SETUPTOOLS_VERSION",
            "PYTHON_GET_PIP_SHA256",
            "PYTHON_GET_PIP_URL",
            "GPG_KEY",
        }
        if image[0].get("Config", {}).get("Volumes"):
            raise SandboxUnavailable("Image-declared writable volumes are forbidden")
        for item in image[0].get("Config", {}).get("Env", []):
            if item.split("=", 1)[0] not in allowed or redact(item) != item:
                raise SandboxUnavailable("Image environment has unapproved variables")
        return {
            "backend": "rootless-gvisor",
            "image": self.image,
            "network": "none",
            "memory_bytes": 268435456,
            "cpus": 1,
            "pids": 32,
            "root_readonly": True,
        }

    def create_command(self, directory: Path) -> list[str]:
        if any(c in str(directory) for c in (",", "\n", "\r")):
            raise ForgeError("Container staging path is not a safe mount CSV value")
        return [
            "create",
            "--pull=never",
            "--interactive",
            "--runtime=runsc",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges=true",
            "--pids-limit=32",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=1",
            "--user=65534:65534",
            "--ipc=none",
            "--log-driver=none",
            "--no-healthcheck",
            "--cgroupns=private",
            "--ulimit=nofile=64:64",
            "--ulimit=fsize=16777216:16777216",
            "--ulimit=core=0:0",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--mount",
            f"type=bind,src={directory},dst=/skill,readonly",
            "--workdir=/skill",
            "--env=PATH=/usr/local/bin:/usr/bin:/bin",
            "--env=LANG=C.UTF-8",
            "--env=PYTHONUTF8=1",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint=python",
            self.image,
            "-I",
            "-B",
            "/skill/scripts/main.py",
        ]

    def attest_created(self, identifier: str, staged: Path) -> dict:
        """Read back daemon-applied settings before any guest process starts."""
        value = strict_json(self._call("inspect", identifier))
        if not isinstance(value, list) or len(value) != 1:
            raise SandboxUnavailable("Container settings cannot be attested")
        instance = value[0]
        host = instance.get("HostConfig", {})
        expected = {
            "Runtime": "runsc",
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "Memory": 268435456,
            "MemorySwap": 268435456,
            "NanoCpus": 1000000000,
            "PidsLimit": 32,
            "IpcMode": "none",
            "CgroupnsMode": "private",
        }
        if (
            any(host.get(k) != v for k, v in expected.items())
            or instance.get("Config", {}).get("User") != "65534:65534"
        ):
            raise SandboxUnavailable("Container resource/isolation settings differ from policy")
        security = host.get("SecurityOpt", [])
        if (
            host.get("CapDrop") != ["ALL"]
            or not any(v in {"no-new-privileges", "no-new-privileges=true"} for v in security)
            or any("unconfined" in v for v in security)
        ):
            raise SandboxUnavailable("Container capabilities/security settings differ from policy")
        mounts = instance.get("Mounts", [])
        binds = [m for m in mounts if m.get("Type") in {"bind", "volume"}]
        if (
            len(binds) != 1
            or binds[0].get("Type") != "bind"
            or binds[0].get("Destination") != "/skill"
            or binds[0].get("RW") is not False
            or Path(binds[0].get("Source", "")).resolve() != staged.resolve()
        ):
            raise SandboxUnavailable("Unexpected or writable host mount")
        return {**expected, "mount_readonly": True, "attested_before_start": True}

    def execute(self, root: Path, inputs: list, spec: dict) -> dict:
        policy = self.preflight()
        deadline = time.monotonic() + self.timeout
        results = []
        with tempfile.TemporaryDirectory(prefix="agentforge-container-") as tmp:
            staged = Path(tmp)
            for source in files(root):
                relative = source.relative_to(root)
                if relative.parts[0] == "scripts":
                    target = staged / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            for value in inputs:
                try:
                    Draft202012Validator(spec["inputs"]).validate(value)
                except ValidationError as exc:
                    results.append(
                        {
                            "ok": False,
                            "error_type": "ValidationError",
                            "error": redact(str(exc))[:1000],
                        }
                    )
                    continue
                if time.monotonic() >= deadline:
                    return {
                        "status": "blocked",
                        "results": results,
                        "error": "Container suite deadline exhausted",
                        "commands": self.commands,
                    }
                identifier = None
                started = time.monotonic()
                try:
                    raw = json.dumps(value, ensure_ascii=True, allow_nan=False)
                    if len(raw) > 32768:
                        raise ForgeError("Container input size limit exceeded")
                    identifier = self._call(*self.create_command(staged)).strip()
                    if not re.fullmatch(r"[a-f0-9]{12,64}", identifier):
                        raise ForgeError("Invalid container identity")
                    applied = self.attest_created(identifier, staged)
                    command = [
                        "docker",
                        "--host",
                        self.socket,
                        "start",
                        "--attach",
                        "--interactive",
                        identifier,
                    ]
                    self.commands.append(command)
                    code, stdout, stderr = self.attach(
                        command, raw, max(0.001, deadline - time.monotonic())
                    )
                    if code:
                        results.append(
                            {
                                "ok": False,
                                "error_type": "GuestExecutionError",
                                "exit_code": code,
                                "stdout": redact(stdout),
                                "stderr": redact(stderr),
                            }
                        )
                    else:
                        output = strict_json(stdout)
                        Draft202012Validator(spec["outputs"]).validate(output)
                        results.append(
                            {
                                "ok": True,
                                "output": output,
                                "exit_code": code,
                                "seconds": time.monotonic() - started,
                                "applied_isolation": applied,
                            }
                        )
                except SandboxUnavailable as exc:
                    return {
                        "status": "blocked",
                        "results": [],
                        "error": str(exc),
                        "commands": self.commands,
                    }
                except (ForgeError, ValueError, ValidationError, subprocess.TimeoutExpired) as exc:
                    results.append(
                        {
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": redact(str(exc))[:1000],
                        }
                    )
                finally:
                    if identifier and re.fullmatch(r"[a-f0-9]{12,64}", identifier):
                        self._call("rm", "--force", identifier)
        return {
            "status": "completed",
            "results": results,
            "commands": self.commands,
            "isolation": policy,
            "exit_code": 0,
            "note": "Per-case exit codes are actual guest process codes; all containers are removed",
        }
