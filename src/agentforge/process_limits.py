"""OS resource containment for trusted workers; WASM remains the code boundary.

The worker receives no input until resource containment has been established.
Job Objects constrain committed memory on Windows. Linux workers install finite
address-space/CPU limits before loading guest code. Neither is a Python sandbox.
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
from ctypes import wintypes

from .core import ForgeError


class ResourceContainmentError(ForgeError):
    pass


class WindowsJob:
    def __init__(self, process: subprocess.Popen, memory_bytes: int, cpu_seconds: float):
        if os.name != "nt":
            raise ResourceContainmentError("Job Objects require Windows")

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        self._type = Extended
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ResourceContainmentError("CreateJobObject failed; guest execution refused")
        limits = Extended()
        # KILL_ON_JOB_CLOSE, PROCESS_MEMORY, JOB_MEMORY, ACTIVE_PROCESS, JOB_TIME.
        limits.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8 | 0x4
        # Windows venv python.exe is a launcher which creates the real interpreter.
        # Both processes stay in the same job; no breakaway is permitted.
        limits.basic.active = 2
        limits.basic.job_time = math.ceil(cpu_seconds) * 10_000_000
        limits.process_memory = limits.job_memory = memory_bytes
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ) or not self.kernel.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(process._handle))
        ):
            self.close()
            raise ResourceContainmentError("Job assignment/limits failed; guest execution refused")
        self.expected = memory_bytes

    def evidence(self) -> dict:
        current = self._type()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 9, ctypes.byref(current), ctypes.sizeof(current), None
        ):
            raise ResourceContainmentError("Cannot verify Job limits")
        if current.process_memory != self.expected or current.basic.active != 2:
            raise ResourceContainmentError("Job limits differ from policy")
        return {
            "backend": "windows-job-object",
            "enforced": True,
            "process_commit_limit_bytes": current.process_memory,
            "job_commit_limit_bytes": current.job_memory,
            "active_process_limit": current.basic.active,
            "cpu_user_seconds": current.basic.job_time / 10_000_000,
            "kill_on_close": bool(current.basic.flags & 0x2000),
            "peak_process_commit_bytes": current.peak_process,
        }

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def linux_worker_limits(memory_bytes: int, cpu_seconds: float) -> dict:
    """Called inside the trusted worker before compiling/instantiating a guest."""
    import resource

    expected_parent = os.environ.get("AGENTFORGE_PARENT_PID")
    if expected_parent is not None:
        if not expected_parent.isdecimal() or os.getppid() != int(expected_parent):
            raise ResourceContainmentError("Worker parent no longer exists")
        # Linux kernel terminates the worker even if its calling CLI is killed.
        if ctypes.CDLL(None, use_errno=True).prctl(1, 9, 0, 0, 0) != 0:
            raise ResourceContainmentError("Cannot install parent-death termination")
        if os.getppid() != int(expected_parent):
            raise ResourceContainmentError("Worker parent exited during containment")

    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    seconds = math.ceil(cpu_seconds)
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    return {
        "backend": "linux-rlimit",
        "enforced": True,
        "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
        "cpu_user_seconds": seconds,
        "core_dump_bytes": 0,
        "parent_death_sigkill": expected_parent is not None,
    }


def bounded_worker(
    command: list[str],
    payload: str,
    *,
    env: dict,
    cwd: str,
    timeout: float,
    memory_bytes: int = 256 * 1024 * 1024,
) -> tuple[subprocess.CompletedProcess, dict]:
    if os.name != "nt" and not os.sys.platform.startswith("linux"):
        raise ResourceContainmentError("No verified OS containment backend on this platform")
    job = None
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
    )
    try:
        if os.name == "nt":
            job = WindowsJob(process, memory_bytes, timeout)
            policy = job.evidence()  # Attest BEFORE stdin can deliver any guest code.
        else:
            policy = {"backend": "linux-rlimit", "enforced_by_trusted_worker": True}
        stdout, stderr = process.communicate(payload, timeout=timeout)
        if job:
            policy = job.evidence()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), policy
    finally:
        if job:
            job.close()  # Kill interpreter descendants before waiting on shared pipes.
        if process.poll() is None:
            process.kill()
        process.communicate()
