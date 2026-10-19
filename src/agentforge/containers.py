"""Fail-closed Python JSON execution in explicitly provisioned rootless gVisor.

Docker/venv/subprocess alone is never accepted as a Python code sandbox. Images
must already exist locally under an approved immutable digest. No pulls/builds,
package installation, privileged containers or writable host mounts are performed.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .core import ForgeError, files, redact, strict_json
from .leases import LeaseStore, reap
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
        lease_dir: str | Path | None = None,
        control=None,
        attach=None,
    ):
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ForgeError("Container timeout must be finite and at most 30 seconds")
        self.image, self.socket, self.timeout = image, socket, timeout
        self.lease_dir = Path(lease_dir) if lease_dir else None
        self.mock_control = control is not None
        self.control = control or self._control
        self.attach = attach or capped_attach
        self.commands = []

    def lease_store(self) -> LeaseStore:
        if not self.lease_dir:
            raise SandboxUnavailable("Python execution requires a durable lease_dir and supervisor")
        return LeaseStore(self.lease_dir, str(self.socket) + "\n" + str(self.image))

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
        if not self.mock_control:
            import stat

            if not os.sys.platform.startswith("linux") or os.getuid() == 0:
                raise SandboxUnavailable("Python containers require a nonroot Linux operator")
            selected = Path(self.socket.removeprefix("unix://"))
            info_socket = selected.lstat()
            info_directory = selected.parent.stat()
            if (
                selected.is_symlink()
                or not stat.S_ISSOCK(info_socket.st_mode)
                or info_socket.st_uid != os.getuid()
                or info_socket.st_mode & 0o002
                or info_directory.st_uid != os.getuid()
                or info_directory.st_mode & 0o077
                or selected.parent.is_symlink()
                or selected.parent != Path("/run/user") / str(os.getuid())
            ):
                raise SandboxUnavailable(
                    "Rootless socket ownership or permissions differ from policy"
                )
        info = json.loads(self._call("info", "--format", "{{json .}}"))
        options = " ".join(info.get("SecurityOptions", []))
        if (
            info.get("OSType") != "linux"
            or info.get("CgroupVersion") != "2"
            or info.get("CgroupDriver") != "systemd"
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

    def create_command(self, directory: Path, name: str | None = None) -> list[str]:
        if any(c in str(directory) for c in (",", "\n", "\r")):
            raise ForgeError("Container staging path is not a safe mount CSV value")
        return [
            "create",
            *(
                [
                    "--name",
                    name,
                    "--label=org.agentforge.managed=1",
                    "--label=org.agentforge.policy=" + self.lease_store().policy,
                    "--label=org.agentforge.lease=" + name,
                ]
                if name
                else []
            ),
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
            "--ulimit=nproc=32:32",
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

    def attest_created(self, identifier: str, staged: Path, name: str) -> dict:
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
            "AutoRemove": False,
        }
        if (
            any(host.get(k) != v for k, v in expected.items())
            or instance.get("Config", {}).get("User") != "65534:65534"
            or instance.get("Config", {}).get("Entrypoint") != ["python"]
            or instance.get("Config", {}).get("Cmd") != ["-I", "-B", "/skill/scripts/main.py"]
            or instance.get("Config", {}).get("WorkingDir") != "/skill"
        ):
            raise SandboxUnavailable("Container resource/isolation settings differ from policy")
        labels = instance["Config"].get("Labels", {})
        if (
            labels.get("org.agentforge.managed") != "1"
            or labels.get("org.agentforge.lease") != name
            or labels.get("org.agentforge.policy") != self.lease_store().policy
            or instance.get("Name") != "/" + name
        ):
            raise SandboxUnavailable("Container identity labels differ from the durable lease")
        if (
            host.get("RestartPolicy", {}).get("Name") not in {"no", ""}
            or host.get("LogConfig", {}).get("Type") != "none"
            or any(
                host.get(k)
                for k in [
                    "Devices",
                    "DeviceRequests",
                    "VolumesFrom",
                    "PortBindings",
                    "PublishAllPorts",
                    "ExtraHosts",
                ]
            )
            or any(host.get(k) == "host" for k in ["PidMode", "UTSMode", "UsernsMode"])
            or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777"}
        ):
            raise SandboxUnavailable("Container auxiliary isolation settings differ from policy")
        limits = {item["Name"]: (item["Soft"], item["Hard"]) for item in host.get("Ulimits", [])}
        if limits != {
            "nofile": (64, 64),
            "fsize": (16777216, 16777216),
            "core": (0, 0),
            "nproc": (32, 32),
        }:
            raise SandboxUnavailable("Container file/resource limits differ from policy")
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

    def remove_leased(self, name: str) -> bool:
        store = self.lease_store()
        if not store.lookup(name):
            raise SandboxUnavailable("Container has no matching local lease")
        identifiers = (
            self._call(
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                "name=^/" + name + "$",
                "--format",
                "{{.ID}}",
            )
            .strip()
            .splitlines()
        )
        if not identifiers:
            return True
        if len(identifiers) != 1 or not re.fullmatch(r"[a-f0-9]{64}", identifiers[0]):
            raise SandboxUnavailable("Cannot identify leased container for cleanup")
        instance = strict_json(self._call("inspect", identifiers[0]))[0]
        labels = instance.get("Config", {}).get("Labels", {})
        if (
            instance.get("Name") != "/" + name
            or labels.get("org.agentforge.managed") != "1"
            or labels.get("org.agentforge.lease") != name
            or labels.get("org.agentforge.policy") != store.policy
        ):
            raise SandboxUnavailable("Cleanup refuses a container with mismatching identity")
        self._call("rm", "--force", identifiers[0])
        return True

    def sweep(self) -> dict:
        store = self.lease_store()
        inventory = (
            self._call(
                "ps",
                "--all",
                "--filter",
                "label=org.agentforge.managed=1",
                "--filter",
                "label=org.agentforge.policy=" + store.policy,
                "--format",
                "{{.Names}}",
            )
            .strip()
            .splitlines()
        )
        return reap(store, self.remove_leased, inventory)

    def supervise(self, *, once: bool = False) -> dict:
        self.preflight()
        store, owner = self.lease_store(), uuid.uuid4().hex
        while True:
            report = self.sweep()
            if report["failed"]:
                raise SandboxUnavailable("Sandbox cleanup failed; heartbeat withdrawn")
            store.heartbeat(owner)
            if once:
                return report
            time.sleep(0.5)

    def execute(self, root: Path, inputs: list, spec: dict) -> dict:
        policy = self.preflight()
        store = self.lease_store()
        try:
            policy["supervisor"] = store.require_reaper()
        except ForgeError as exc:
            raise SandboxUnavailable(str(exc)) from exc
        if len(inputs) > 128:
            raise ForgeError("Container case count exceeds 128")
        sources = [
            (p, p.relative_to(root))
            for p in files(root)
            if p.relative_to(root).parts[0] == "scripts"
        ]
        deadline = time.monotonic() + self.timeout
        results = []
        for value in inputs:
            try:
                Draft202012Validator(spec["inputs"]).validate(value)
            except ValidationError as exc:
                results.append(
                    {"ok": False, "error_type": "ValidationError", "error": redact(str(exc))[:1000]}
                )
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "status": "blocked",
                    "results": results,
                    "error": "Container suite deadline exhausted",
                    "commands": self.commands,
                }
            name = store.reserve(remaining)
            staged = store.staging(name)
            staged.mkdir(mode=0o755)
            staged.chmod(0o755)
            cleanup_error = None
            started = time.monotonic()
            try:
                for source, relative in sources:
                    target = staged / relative
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    shutil.copyfile(source, target)
                    target.chmod(0o644)
                for directory in staged.rglob("*"):
                    if directory.is_dir():
                        directory.chmod(0o755)
                raw = json.dumps(value, ensure_ascii=True, allow_nan=False)
                if len(raw) > 32768:
                    raise ForgeError("Container input size limit exceeded")
                identifier = self._call(*self.create_command(staged, name)).strip()
                if not re.fullmatch(r"[a-f0-9]{64}", identifier):
                    raise ForgeError("Invalid container identity")
                store.update(name, "created")
                applied = self.attest_created(identifier, staged, name)
                store.require_reaper()
                row = store.lookup(name)
                if row is None or store.is_expired(row):
                    raise ForgeError("Container lease expired before guest start")
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
                store.update(name, "running")
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
                cleanup_error = str(exc)
            except (
                ForgeError,
                ValueError,
                ValidationError,
                subprocess.TimeoutExpired,
                OSError,
            ) as exc:
                results.append(
                    {
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": redact(str(exc))[:1000],
                    }
                )
            finally:
                # Name was recorded before create; cleanup works even if the response was lost.
                store.update(name, "cleanup-pending")
                try:
                    self.remove_leased(name)
                    store.remove_staging(name)
                    store.update(name, "closed")
                except (ForgeError, OSError, ValueError) as exc:
                    store.update(name, "cleanup-pending", type(exc).__name__)
                    cleanup_error = "Container cleanup pending; durable supervisor will retry"
            if cleanup_error:
                return {
                    "status": "blocked",
                    "results": [],
                    "error": cleanup_error,
                    "commands": self.commands,
                }
        return {
            "status": "completed",
            "results": results,
            "commands": self.commands,
            "isolation": policy,
            "exit_code": 0,
            "note": "Guest exit codes recorded; normal cleanup verified and crash leases supervised",
        }
