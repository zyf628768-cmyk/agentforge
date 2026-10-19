import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentforge.artifacts import BundleGenerator
from agentforge.containers import PythonContainer, capped_attach
from agentforge.core import ForgeError, read_json
from agentforge.process_limits import ResourceContainmentError, bounded_worker
from agentforge.sandbox import SandboxUnavailable, worker_environment
from agentforge.testing import evaluate

FIXTURES = Path(__file__).resolve().parents[1] / "examples/v02"
IMAGE = "python@sha256:" + "1" * 64
SOCKET = "unix:///run/user/1000/docker.sock"


@pytest.mark.skipif(os.name != "nt", reason="Windows Python 3.11 architecture bootstrap")
def test_worker_architecture_is_derived_without_inheriting_host_data(monkeypatch):
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "untrusted-host-value")
    monkeypatch.setenv("AGENTFORGE_SECRET_CANARY", "private-value")
    monkeypatch.setattr("agentforge.sandbox.sysconfig.get_platform", lambda: "win-amd64")
    env = worker_environment()
    assert env == {"SYSTEMROOT": os.environ["SYSTEMROOT"], "PROCESSOR_ARCHITECTURE": "AMD64"}
    monkeypatch.setattr("agentforge.sandbox.sysconfig.get_platform", lambda: "unknown")
    with pytest.raises(SandboxUnavailable, match="architecture"):
        worker_environment()


def docker_info():
    return {
        "OSType": "linux",
        "CgroupVersion": "2",
        "CgroupDriver": "systemd",
        "SecurityOptions": ["name=rootless", "name=seccomp,profile=builtin"],
        "Runtimes": {"runsc": {}},
        "Warnings": [],
    }


def control(command):
    if "info" in command:
        return json.dumps(docker_info())
    if "inspect" in command:
        return json.dumps([{"RepoDigests": [IMAGE], "Config": {"Env": ["PATH=/usr/bin"]}}])
    if "create" in command:
        return "a" * 64
    if "rm" in command:
        return "a" * 64
    raise AssertionError(command)


def attesting_control(override=None):
    staged = None

    def call(command):
        nonlocal staged
        if "create" in command:
            mount = next(c for c in command if c.startswith("type=bind,src="))
            staged = mount.split("src=", 1)[1].split(",dst=", 1)[0]
            return "a" * 64
        if "inspect" in command and command[-1] == "a" * 64:
            host = {
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
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true"],
            }
            host.update(override or {})
            return json.dumps(
                [
                    {
                        "HostConfig": host,
                        "Config": {"User": "65534:65534"},
                        "Mounts": [
                            {"Type": "bind", "Destination": "/skill", "Source": staged, "RW": False}
                        ],
                    }
                ]
            )
        return control(command)

    return call


def test_python_artifact_is_generated_but_host_execution_refused(tmp_path):
    root = BundleGenerator.from_file(FIXTURES / "csv-summary.bundle.json").generate(
        read_json(FIXTURES / "csv-summary.plan.json"), tmp_path / "csv-summary"
    )
    report = evaluate(root, evaluation_path=FIXTURES / "csv-summary.evaluation.json")
    assert report["checks"]["passed"]
    assert report["status"] == "blocked" and not report["cases"]
    assert "approved local image" in report["execution"]["error"]


@pytest.mark.parametrize(
    "override",
    [
        {"CgroupVersion": "1"},
        {"SecurityOptions": ["name=seccomp"]},
        {"Runtimes": {}},
        {"Warnings": ["No memory limit support"]},
        {"CgroupDriver": "none"},
    ],
)
def test_container_preflight_refuses_weak_environment(override):
    def fake(command):
        value = docker_info() | override
        return json.dumps(value)

    with pytest.raises(SandboxUnavailable):
        PythonContainer(image=IMAGE, socket=SOCKET, control=fake).preflight()


def test_remote_docker_and_mutable_images_are_not_accepted():
    for image, socket in [("python:latest", SOCKET), (IMAGE, "tcp://prod:2375"), (IMAGE, None)]:
        with pytest.raises(SandboxUnavailable):
            PythonContainer(
                image=image,
                socket=socket,
                control=lambda c: pytest.fail("No control call is allowed"),
            ).preflight()


def test_container_protocol_pins_controls_and_cleans_after_execution(tmp_path):
    root = BundleGenerator.from_file(FIXTURES / "csv-summary.bundle.json").generate(
        read_json(FIXTURES / "csv-summary.plan.json"), tmp_path / "csv-summary"
    )
    spec = read_json(root / "spec.json")
    container = PythonContainer(
        image=IMAGE,
        socket=SOCKET,
        control=attesting_control(),
        attach=lambda command, data, timeout: (0, '{"count":2,"sum":6,"mean":3}', ""),
    )
    result = container.execute(root, [read_json(root / "examples/input.json")], spec)
    assert result["results"][0]["ok"]
    command = next(c for c in container.commands if "create" in c)
    for expected in [
        "--pull=never",
        "--runtime=runsc",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--memory=256m",
        "--pids-limit=32",
        "--cpus=1",
        "--user=65534:65534",
    ]:
        assert expected in command
    assert "--privileged" not in command
    assert "--force" in container.commands[-1] and "rm" in container.commands[-1]
    assert all(c[:3] == ["docker", "--host", SOCKET] for c in container.commands)


def test_container_timeout_still_removes_guest(tmp_path):
    root = BundleGenerator.from_file(FIXTURES / "csv-summary.bundle.json").generate(
        read_json(FIXTURES / "csv-summary.plan.json"), tmp_path / "csv-summary"
    )

    def timed_out(*args):
        raise subprocess.TimeoutExpired("docker", 0.1)

    container = PythonContainer(
        image=IMAGE, socket=SOCKET, control=attesting_control(), attach=timed_out
    )
    report = container.execute(
        root, [read_json(root / "examples/input.json")], read_json(root / "spec.json")
    )
    assert not report["results"][0]["ok"]
    assert "rm" in container.commands[-1]


def test_container_image_cannot_supply_secret_environment():
    def unsafe(command):
        if "inspect" in command:
            return json.dumps([{"RepoDigests": [IMAGE], "Config": {"Env": ["API_KEY=fake-value"]}}])
        return control(command)

    with pytest.raises(SandboxUnavailable, match="environment"):
        PythonContainer(image=IMAGE, socket=SOCKET, control=unsafe).preflight()


def test_daemon_settings_are_checked_before_guest_start(tmp_path):
    root = BundleGenerator.from_file(FIXTURES / "csv-summary.bundle.json").generate(
        read_json(FIXTURES / "csv-summary.plan.json"), tmp_path / "csv-summary"
    )
    container = PythonContainer(
        image=IMAGE,
        socket=SOCKET,
        control=attesting_control({"Memory": 0}),
        attach=lambda *a: pytest.fail("Unbounded guest must never start"),
    )
    result = container.execute(
        root, [read_json(root / "examples/input.json")], read_json(root / "spec.json")
    )
    assert result["status"] == "blocked"
    assert "rm" in container.commands[-1]


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows Job resource enforcement probe")
def test_actual_windows_process_memory_quota(tmp_path):
    script = tmp_path / "trusted_memory_probe.py"
    script.write_text(
        "import sys\nsys.stdin.read()\ntry:\n    x=bytearray(128*1024*1024)\n    print('escaped')\nexcept MemoryError:\n    print('allocation-denied')\n",
        encoding="utf-8",
    )
    result, limits = bounded_worker(
        [sys.executable, "-I", str(script)],
        "go",
        cwd=str(tmp_path),
        env={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
        timeout=3,
        memory_bytes=64 * 1024 * 1024,
    )
    assert result.returncode == 0 and result.stdout.strip() == "allocation-denied"
    assert limits["enforced"] and limits["job_commit_limit_bytes"] == 64 * 1024 * 1024


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows Job process-tree termination probe")
def test_actual_windows_watchdog_kills_interpreter_descendant(tmp_path):
    script = tmp_path / "trusted_timeout_probe.py"
    script.write_text("import sys\nsys.stdin.read()\nwhile True:\n    pass\n", encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_worker(
            [sys.executable, "-I", str(script)],
            "go",
            cwd=str(tmp_path),
            env={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
            timeout=0.3,
        )
    assert time.monotonic() - started < 2


@pytest.mark.skipif(os.name != "nt", reason="Windows Job assignment failure path")
def test_containment_failure_never_delivers_payload(tmp_path, monkeypatch):
    from agentforge import process_limits

    script = tmp_path / "trusted_handshake_probe.py"
    marker = tmp_path / "payload-delivered"
    script.write_text(
        f"import sys\nfrom pathlib import Path\nif sys.stdin.read(): Path({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8",
    )

    def denied(*args):
        raise ResourceContainmentError("simulated assignment refusal")

    monkeypatch.setattr(process_limits, "WindowsJob", denied)
    with pytest.raises(ResourceContainmentError):
        bounded_worker(
            [sys.executable, "-I", str(script)],
            "sensitive-payload",
            cwd=str(tmp_path),
            env={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
            timeout=1,
        )
    assert not marker.exists()


def test_output_flood_is_capped_without_retaining_unbounded_bytes(tmp_path):
    script = tmp_path / "trusted_output_probe.py"
    script.write_text("print('x'*1000000)\n", encoding="utf-8")
    with pytest.raises(ForgeError, match="output exceeded"):
        capped_attach([sys.executable, "-I", str(script)], "", 3)
