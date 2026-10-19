import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def evidence_module():
    path = Path(__file__).resolve().parents[1] / "tools/container_evidence.py"
    spec = importlib.util.spec_from_file_location("container_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "failure",
    [
        {"error_type": "SandboxUnavailable"},
        {"error_type": "GuestExecutionError", "exit_code": 1, "stderr": "SyntaxError"},
        {"error_type": "GuestExecutionError", "exit_code": 137},
        {"error_type": "GuestExecutionError", "exit_code": 1, "stderr": "MemoryErrorImitation"},
    ],
)
def test_unrelated_failures_are_not_reported_as_memory_qualification(failure):
    with pytest.raises(AssertionError):
        evidence_module().assert_memory_denial(failure)


def test_memory_qualification_requires_specific_failure_evidence():
    module = evidence_module()
    module.assert_memory_denial(
        {"error_type": "GuestExecutionError", "exit_code": 1, "stderr": "Traceback:\nMemoryError\n"}
    )
    module.assert_memory_denial(
        {"error_type": "GuestExecutionError", "exit_code": 137, "termination": {"oom_killed": True}}
    )


def test_kernel_probe_refuses_unbounded_or_unenforced_controls(tmp_path):
    module = evidence_module()
    proc = tmp_path / "proc/42"
    proc.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/scope\n")
    cgroups = tmp_path / "cgroups"
    leaf = cgroups / "scope"
    leaf.mkdir(parents=True)
    for name, value in {
        "cpu.max": "100000 100000",
        "memory.max": "268435456",
        "pids.max": "32",
        "pids.current": "20",
        "pids.events": "max 0\n",
        "cpu.stat": "nr_throttled 0\n",
        "memory.events": "oom_kill 0\n",
    }.items():
        (leaf / name).write_text(value)
    observed = module.kernel_snapshot(42, proc=proc.parent, cgroups=cgroups)
    module.assert_limits(observed)
    for name in ("cpu.max", "memory.max", "pids.max"):
        unbounded = {**observed, name: "max 100000" if name == "cpu.max" else "max"}
        with pytest.raises(AssertionError):
            module.assert_limits(unbounded)
    (proc / "cgroup").write_text("0::/../escape\n")
    with pytest.raises(ValueError):
        module.kernel_snapshot(42, proc=proc.parent, cgroups=cgroups)


def test_pid_quota_requires_an_actual_kernel_event_increase():
    module = evidence_module()
    assert not module.pid_limit_hit([])
    assert not module.pid_limit_hit([{"pids.events": "max 0"}, {"pids.events": "max 0"}])
    assert module.pid_limit_hit([{"pids.events": "max 0"}, {"pids.events": "max 1"}])


@pytest.mark.parametrize("kind", ["output", "wall"])
@pytest.mark.parametrize(
    "report",
    [
        {"status": "blocked", "results": [], "error": "Supervisor unavailable"},
        {"status": "completed", "results": [{"ok": False, "error_type": "SandboxUnavailable"}]},
        {"status": "completed", "results": [{"ok": False, "error_type": "GuestExecutionError"}]},
        {"status": "completed", "results": [{"ok": True, "output": {}}]},
    ],
)
def test_unrelated_outcomes_never_qualify_output_or_wall_limits(kind, report):
    with pytest.raises(AssertionError):
        evidence_module().assert_bounded_failure(report, kind)


def test_specific_stream_denial_and_observed_watchdog_qualify():
    module = evidence_module()
    module.assert_bounded_failure(
        {
            "status": "completed",
            "results": [
                {
                    "ok": False,
                    "error_type": "ForgeError",
                    "error": "Container output exceeded 64 KiB stream limit",
                }
            ],
        },
        "output",
    )
    wall = {"status": "completed", "results": [{"ok": False, "error_type": "TimeoutExpired"}]}
    with pytest.raises(AssertionError):
        module.assert_bounded_failure(wall, "wall")
    module.assert_bounded_failure({**wall, "kernel_samples": [{"pids.max": "32"}]}, "wall")


def test_crash_caller_bootstraps_in_isolated_python_mode():
    helper = Path(__file__).resolve().parents[1] / "tools/qualify_crash_child.py"
    result = subprocess.run(
        [sys.executable, "-I", str(helper), "--help"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert "--container-config" in result.stdout
