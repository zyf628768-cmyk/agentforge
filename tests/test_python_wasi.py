import hashlib
import json

import pytest

from agentforge.core import ForgeError
from agentforge.python_wasi import PythonWasi, python_runtime
from agentforge.sandbox import SandboxUnavailable


def sealed(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.wasm").write_bytes(b"not executed")
    (runtime / "LICENSE").write_text("test fixture")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.iterdir()}
    manifest = runtime / "runtime-manifest.json"
    manifest.write_text(json.dumps({"files": hashes}))
    return runtime, hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_policy_requires_explicit_runtime_and_hash(tmp_path):
    with pytest.raises(SandboxUnavailable, match="approved"):
        PythonWasi(runtime_dir=tmp_path, manifest_sha256="").preflight()
    with pytest.raises(SandboxUnavailable, match="not installed"):
        PythonWasi(runtime_dir=tmp_path, manifest_sha256="a" * 64).preflight()
    for timeout in [0, -1, 31, float("nan"), float("inf")]:
        with pytest.raises(ForgeError):
            PythonWasi(runtime_dir=tmp_path, manifest_sha256="a" * 64, timeout=timeout)


@pytest.mark.parametrize("attack", ["module", "manifest", "extra", "missing", "skill"])
def test_runtime_integrity_refuses_before_worker(tmp_path, attack, monkeypatch):
    runtime, digest = sealed(tmp_path)
    if attack == "module":
        (runtime / "python.wasm").write_bytes(b"changed")
    elif attack == "manifest":
        (runtime / "runtime-manifest.json").write_text("{}")
    elif attack == "extra":
        (runtime / "extra.py").write_text("unapproved")
    elif attack == "missing":
        (runtime / "LICENSE").unlink()
    else:
        (tmp_path / "manifest.json").write_text("{}")
    monkeypatch.setattr(
        "agentforge.python_wasi.bounded_worker", lambda *a, **kw: pytest.fail("No guest may run")
    )
    with pytest.raises(SandboxUnavailable):
        PythonWasi(runtime_dir=runtime, manifest_sha256=digest).execute(tmp_path, [], {})


def test_explicit_selection_never_falls_back(tmp_path):
    from agentforge.containers import PythonContainer

    assert isinstance(python_runtime(None), PythonContainer)
    runtime, digest = sealed(tmp_path)
    selected = python_runtime(
        {"backend": "python-wasi", "runtime_dir": str(runtime), "manifest_sha256": digest}
    )
    assert isinstance(selected, PythonWasi)
    policy = selected.preflight()
    assert not policy["network"] and not policy["host_environment_inherited"]
    assert not policy["native_guest_processes"]
    with pytest.raises(ForgeError, match="Unknown"):
        python_runtime({"backend": "native-python"})
    with pytest.raises(ForgeError, match="exactly"):
        python_runtime(
            {
                "backend": "python-wasi",
                "runtime_dir": str(runtime),
                "manifest_sha256": digest,
                "network": True,
            }
        )


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux kernel parent death")
def test_linux_worker_is_terminated_after_parent_killed(tmp_path):
    import subprocess
    import sys
    import time

    # Trusted test helpers; no generated Python is executed on the host.
    marker = tmp_path / "child.pid"
    worker = tmp_path / "trusted_child.py"
    worker.write_text(
        "from agentforge.process_limits import linux_worker_limits\n"
        "import os,time\nfrom pathlib import Path\n"
        "linux_worker_limits(256*1024*1024, 5)\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    parent = tmp_path / "trusted_parent.py"
    parent.write_text(
        "import os,sys,subprocess,time\n"
        f"subprocess.Popen([sys.executable,'-I',{str(worker)!r}],"
        "env={'AGENTFORGE_PARENT_PID': str(os.getpid())})\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen([sys.executable, "-I", str(parent)])
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        child = int(marker.read_text())
        process.kill()
        process.wait(timeout=2)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = __import__("pathlib").Path(f"/proc/{child}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("Contained worker survived parent death")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
