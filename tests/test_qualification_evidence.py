import importlib.util
from pathlib import Path

import pytest


def evidence_module():
    path = Path(__file__).resolve().parents[1] / "tools/container_evidence.py"
    spec = importlib.util.spec_from_file_location("container_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", [
    {"error_type": "SandboxUnavailable"},
    {"error_type": "GuestExecutionError", "exit_code": 1, "stderr": "SyntaxError"},
    {"error_type": "GuestExecutionError", "exit_code": 137},
    {"error_type": "GuestExecutionError", "exit_code": 1, "stderr": "MemoryErrorImitation"},
])
def test_unrelated_failures_are_not_reported_as_memory_qualification(failure):
    with pytest.raises(AssertionError):
        evidence_module().assert_memory_denial(failure)


def test_memory_qualification_requires_specific_failure_evidence():
    module = evidence_module()
    module.assert_memory_denial({"error_type": "GuestExecutionError", "exit_code": 1,
                                 "stderr": "Traceback:\nMemoryError\n"})
    module.assert_memory_denial({"error_type": "GuestExecutionError", "exit_code": 137,
                                 "termination": {"oom_killed": True}})


def test_kernel_probe_refuses_unbounded_or_unenforced_controls(tmp_path):
    module = evidence_module()
    proc = tmp_path / "proc/42"
    proc.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/scope\n")
    cgroups = tmp_path / "cgroups"
    leaf = cgroups / "scope"
    leaf.mkdir(parents=True)
    for name, value in {"cpu.max": "100000 100000", "memory.max": "268435456",
                        "pids.max": "32", "cpu.stat": "nr_throttled 0\n",
                        "memory.events": "oom_kill 0\n"}.items():
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
