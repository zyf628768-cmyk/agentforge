"""Read actual kernel controls on the disposable qualification host."""

import re
from pathlib import Path, PurePosixPath


def kernel_snapshot(pid: int, *, proc=Path("/proc"), cgroups=Path("/sys/fs/cgroup")):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Require a live positive host PID")
    records = (proc / str(pid) / "cgroup").read_text(encoding="ascii").splitlines()
    unified = [line.removeprefix("0::") for line in records if line.startswith("0::")]
    if len(unified) != 1:
        raise ValueError("Require one unified kernel cgroup")
    relative = PurePosixPath(unified[0])
    if not relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid kernel cgroup path")
    root = cgroups.resolve()
    directory = (root / str(relative).lstrip("/")).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Kernel cgroup escaped its mount")
    values = {
        name: (directory / name).read_text(encoding="ascii").strip()
        for name in ("cpu.max", "memory.max", "pids.max", "cpu.stat", "memory.events")
    }
    values["cgroup"] = str(relative)
    return values


def assert_limits(snapshot):
    quota, period = snapshot["cpu.max"].split()
    if quota == "max" or int(period) <= 0 or int(quota) != int(period):
        raise AssertionError("Kernel CPU bandwidth differs from one CPU")
    if snapshot["memory.max"] != "268435456" or snapshot["pids.max"] != "32":
        raise AssertionError("Kernel memory/PID controls differ from policy")


def cpu_throttled(samples):
    if len(samples) < 2:
        return False
    values = [dict(line.split() for line in sample["cpu.stat"].splitlines()) for sample in samples]
    return int(values[-1]["nr_throttled"]) > int(values[0]["nr_throttled"])


def assert_memory_denial(failure):
    if failure.get("error_type") != "GuestExecutionError":
        raise AssertionError("An unrelated engine failure is not a memory denial")
    oom = failure.get("termination", {}).get("oom_killed") is True
    memory_error = failure.get("exit_code") == 1 and re.search(
        r"(?m)^MemoryError(?::.*)?$", failure.get("stderr", "")
    )
    if not (oom or memory_error):
        raise AssertionError("Require actual OOM evidence or a Python MemoryError")
