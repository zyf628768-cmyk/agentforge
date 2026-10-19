"""Opt-in actual rootless-gVisor tests. Never execute a guest on the host.

Requires an explicitly provisioned non-production Linux VM and immutable image.
The only host canary is freshly generated dummy data owned by this test harness.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from container_evidence import assert_limits, cpu_throttled, kernel_snapshot

from agentforge.artifacts import BundleGenerator
from agentforge.containers import PythonContainer, capped_attach
from agentforge.core import ForgeError, read_json, write_json
from agentforge.testing import evaluate


def wait_for(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError("Qualification condition was not observed within the deadline")


def qualify(config: dict, output: Path, *, daemon_restart: bool) -> dict:
    if not sys.platform.startswith("linux") or os.getuid() == 0:
        raise ForgeError("Actual qualification requires a nonroot, dedicated Linux test runner")
    if output.exists():
        raise ForgeError("Preserve existing qualification evidence")
    output.mkdir(parents=True)
    output = output.resolve()
    config_path = output / "policy.json"
    write_json(config_path, config)
    runtime = PythonContainer(**config)
    policy = runtime.preflight()  # Must pass BEFORE any adversarial source can be started.
    store = runtime.lease_store()
    records = []
    supervisor = None
    supervisor_log = (output / "supervisor.log").open("w")

    def record(name, evidence):
        records.append({"name": name, "evidence": evidence})
        write_json(output / "checks.json", records, safe=True)
        print("PASS: " + name, flush=True)

    def healthy():
        try:
            store.require_reaper()
            return True
        except ForgeError:
            return False

    def start_supervisor():
        return subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-m",
                "agentforge",
                "sandbox",
                "supervise",
                "--container-config",
                str(config_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=supervisor_log,
            stderr=supervisor_log,
            env={"PATH": os.defpath},
        )

    def guest(name, source, *, timeout=5, observe_kernel=False):
        directory = output / "guests" / name
        (directory / "scripts").mkdir(parents=True)
        (directory / "scripts/main.py").write_text(source, encoding="utf-8")
        # Deliberately bypass static AST heuristics to test the actual code boundary.
        samples = []

        def observed_attach(command, data, seconds):
            stop = threading.Event()

            def observe():
                while not stop.is_set():
                    try:
                        state = json.loads(runtime._call("inspect", command[-1]))[0]["State"]
                        if state.get("Running"):
                            samples.append(kernel_snapshot(state["Pid"]))
                    except (OSError, KeyError, ValueError, ForgeError):
                        pass  # A successful, bound snapshot remains mandatory below.
                    stop.wait(0.05)

            thread = threading.Thread(target=observe)
            thread.start()
            try:
                return capped_attach(command, data, seconds)
            finally:
                stop.set()
                thread.join(timeout=12)
                assert not thread.is_alive(), "Kernel observer did not stop"

        result = PythonContainer(**config, timeout=timeout,
                                 attach=observed_attach if observe_kernel else None).execute(
            directory, [{}], {"inputs": {}, "outputs": {}}
        )
        if observe_kernel:
            result["kernel_samples"] = samples
        write_json(output / (name + ".json"), result, safe=True)
        return result

    try:
        supervisor = start_supervisor()
        wait_for(healthy)
        record("independent-supervisor", store.require_reaper())
        fixtures = Path(__file__).resolve().parents[1] / "examples/v02"
        csv_skill = BundleGenerator.from_file(fixtures / "csv-summary.bundle.json").generate(
            read_json(fixtures / "csv-summary.plan.json"), output / "csv-summary"
        )
        report = evaluate(
            csv_skill,
            output / "csv-report.json",
            evaluation_path=fixtures / "csv-summary.evaluation.json",
            container_config=config,
            timeout=15,
        )
        assert report["status"] == "passed", report
        record("actual-csv-independent-evaluation", report["metrics"])

        canary = output / "dummy-host-canary"
        canary.write_text("public-dummy-test-data")
        os.environ["AGENTFORGE_SECRET_CANARY"] = "public-dummy-test-data"
        listener = socket.create_server(("127.0.0.1", 0))
        # Positive host control: a refused connection is meaningful only when a
        # real host service is reachable at the exact target during the probe.
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass
        try:
            result = guest(
                "host-access",
            f"""import json, os, socket, sys
json.load(sys.stdin)
blocked = []
for path in [{str(canary)!r}, '/etc/agentforge-test-write', '/skill/scripts/main.py']:
    try:
        with open(path, 'r' if path == {str(canary)!r} else 'a') as f:
            if path != {str(canary)!r}: f.write('bad')
        blocked.append(False)
    except OSError: blocked.append(True)
s = socket.socket()
s.settimeout(0.2)
try:
    s.connect(('127.0.0.1', {listener.getsockname()[1]}))
    blocked.append(False)
except OSError: blocked.append(True)
finally: s.close()
blocked.append(os.environ.get('AGENTFORGE_SECRET_CANARY') is None)
blocked.append(os.geteuid() == 65534)
print(json.dumps({{'blocked': blocked}}))
""",
            )
        finally:
            listener.close()
        assert result["results"][0]["output"] == {"blocked": [True] * 6}, result
        assert canary.read_text() == "public-dummy-test-data"
        record("filesystem-network-environment-uid", result)

        control = guest("memory-control", "import sys,json\njson.load(sys.stdin)\nx=bytearray(32*1024**2)\nprint(json.dumps({'allocated':len(x)}))\n")
        assert control["results"][0]["output"] == {"allocated": 32*1024**2}, control
        record("actual-memory-positive-control", control)
        result = guest(
            "memory", "import sys\nsys.stdin.read()\nx=bytearray(1024**3)\nprint('{}')\n"
        )
        failure = result["results"][0]
        assert failure["error_type"] == "GuestExecutionError", result
        assert failure.get("termination", {}).get("oom_killed") or (
            failure["exit_code"] == 1 and "\nMemoryError" in failure.get("stderr", "")
        ), result
        record("actual-memory-quota", result)
        result = guest("cpu-kernel-quota", """import json,os,sys,time
json.load(sys.stdin)
children=[]
for _ in range(2):
    pid=os.fork()
    if pid==0:
        until=time.monotonic()+4
        while time.monotonic()<until: pass
        os._exit(0)
    children.append(pid)
for pid in children: os.waitpid(pid,0)
print(json.dumps({'workers':len(children)}))
""", timeout=12, observe_kernel=True)
        assert result["results"][0]["output"] == {"workers": 2}, result
        assert result["kernel_samples"], "No actual kernel controls were observed"
        for sample in result["kernel_samples"]:
            assert_limits(sample)
        assert cpu_throttled(result["kernel_samples"]), "CPU bandwidth limit did not throttle two workers"
        record("actual-kernel-cpu-memory-pid-controls", result)
        result = guest("output-flood", "print('x'*1000000)\n")
        assert result["status"] == "blocked" or not result["results"][0]["ok"], result
        assert len(json.dumps(result)) < 150000
        record("actual-output-cap", result)
        result = guest("wall-time", "import sys\nsys.stdin.read()\nwhile True: pass\n", timeout=2)
        assert result["status"] == "blocked" or not result["results"][0]["ok"], result
        record("actual-wall-time-kill", result)

        result = guest(
            "fork-limit",
            """import json, os, signal, sys, time
sys.stdin.read()
children=[]
denied=False
try:
    for _ in range(64):
        try: pid=os.fork()
        except OSError:
            denied=True
            break
        if pid==0:
            time.sleep(10)
            os._exit(0)
        children.append(pid)
finally:
    for pid in children:
        try: os.kill(pid, signal.SIGKILL)
        except OSError: pass
    for pid in children:
        try: os.waitpid(pid, 0)
        except OSError: pass
print(json.dumps({'denied':denied,'children':len(children)}))
""",
            timeout=10,
        )
        assert result["results"][0]["output"]["denied"], result
        assert result["results"][0]["output"]["children"] < 32, result
        record("actual-fork-quota", result)

        # Kill the calling CLI after the daemon confirms a running container.
        crash_root = output / "guests/wall-time"
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--crash-child",
                "--container-config",
                str(config_path),
                "--output",
                str(crash_root),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def running():
            for row in store.outstanding():
                if row["state"] == "running":
                    try:
                        instance = json.loads(runtime._call("inspect", row["name"]))[0]
                        if instance.get("State", {}).get("Running"):
                            return True
                    except ForgeError:
                        pass
            return False

        wait_for(running)
        child.kill()
        child.wait(timeout=5)
        wait_for(lambda: not store.outstanding())
        assert not runtime._call(
            "ps",
            "--all",
            "--filter",
            "label=org.agentforge.policy=" + store.policy,
            "--format",
            "{{.ID}}",
        ).strip()
        record("calling-cli-killed-container-reaped", {"child_exit": child.returncode})

        outage_child = None
        if daemon_restart:
            outage_child = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--crash-child",
                    "--container-config",
                    str(config_path),
                    "--output",
                    str(crash_root),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for(running)
            outage_child.kill()
            outage_child.wait(timeout=5)
        supervisor.kill()
        supervisor.wait(timeout=5)
        if daemon_restart:
            subprocess.run(["systemctl", "--user", "stop", "docker"], check=True, timeout=30)
            assert store.outstanding()
        time.sleep(5.2)
        assert not healthy()
        try:
            PythonContainer(**config).execute(crash_root, [{}], {"inputs": {}, "outputs": {}})
        except ForgeError:
            record("missing-supervisor-fails-closed", {"refused": True})
        else:
            raise AssertionError("Execution started without a live supervisor")
        if daemon_restart:
            # Only enabled by the explicit disposable-VM qualification invocation.
            subprocess.run(["systemctl", "--user", "start", "docker"], check=True, timeout=30)
        supervisor = start_supervisor()
        wait_for(healthy)
        wait_for(lambda: not store.outstanding())
        record("supervisor-restarted", store.require_reaper())
        assert not store.outstanding()
        if daemon_restart:
            record("daemon-and-supervisor-crash-recovery", {"pending_leases_recovered": True})
        summary = {
            "status": "passed",
            "actual_runtime": True,
            "mocked_daemon": False,
            "policy": policy,
            "checks": len(records),
            "paid_requests": 0,
            "daemon_restart_tested": daemon_restart,
        }
        write_json(output / "summary.json", summary)
        return summary
    finally:
        if supervisor and supervisor.poll() is None:
            supervisor.terminate()
            supervisor.wait(timeout=10)
        supervisor_log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crash-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--restart-disposable-daemon", action="store_true")
    args = parser.parse_args()
    config = read_json(args.container_config)
    if args.crash_child:
        PythonContainer(**config, timeout=3).execute(
            args.output, [{}], {"inputs": {}, "outputs": {}}
        )
    else:
        print(
            json.dumps(
                qualify(config, args.output, daemon_restart=args.restart_disposable_daemon),
                indent=2,
            )
        )
