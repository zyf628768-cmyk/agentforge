"""Trusted bounded worker. Guest source is interpreted only inside CPython WASM."""

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

import wasmtime
from jsonschema import Draft202012Validator

from .core import ForgeError, redact, strict_json
from .process_limits import linux_worker_limits
from .python_wasi import PythonWasi


def execute(job):
    policy = PythonWasi(
        runtime_dir=job["runtime_dir"], manifest_sha256=job["manifest_sha256"]
    ).preflight()
    config = wasmtime.Config()
    config.consume_fuel = True
    config.wasm_threads = False
    config.wasm_memory64 = False
    config.wasm_multi_memory = False
    config.max_wasm_stack = 1024 * 1024
    config.memory_reservation = 64 * 1024 * 1024
    config.memory_guard_size = 65536
    config.cranelift_opt_level = "none"
    config.parallel_compilation = False
    engine = wasmtime.Engine(config)
    module = wasmtime.Module.from_file(engine, str(Path(job["runtime_dir"]) / "python.wasm"))
    if any(item.module != "wasi_snapshot_preview1" for item in module.imports):
        raise ForgeError("Runtime imports are outside the permitted WASI preview1 interface")
    linker = wasmtime.Linker(engine)
    linker.define_wasi()
    results = []
    with tempfile.TemporaryDirectory(prefix="agentforge-wasi-guest-") as tmp:
        staged = Path(tmp) / "skill"
        staged.mkdir()
        for name, encoded in job["sources"].items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "scripts":
                raise ForgeError("Invalid WASI staging path")
            target = staged.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(encoded, validate=True))
        for value in job["inputs"]:
            started = time.monotonic()
            store = None
            wasi = None
            buffers = [bytearray(), bytearray()]
            overflow = [False]

            def sink(index):
                def write(data):
                    remaining = 65536 - len(buffers[index])
                    buffers[index].extend(data[: max(0, remaining)])
                    if len(data) > remaining:
                        overflow[0] = True
                        return -1
                    return len(data)

                return write

            try:
                Draft202012Validator(job["spec"]["inputs"]).validate(value)
                raw = json.dumps(value, ensure_ascii=True, allow_nan=False)
                if len(raw) > 32768:
                    raise ForgeError("WASI Python input exceeds 32 KiB")
                stdin_path = Path(tmp) / "stdin.json"
                stdin_path.write_text(raw, encoding="utf-8")
                wasi = wasmtime.WasiConfig()
                wasi.argv = ["/runtime/python.wasm", "-I", "-B", "/skill/scripts/main.py"]
                wasi.env = [("LANG", "C.UTF-8")]
                wasi.stdin_file = str(stdin_path)
                wasi.stdout_custom = sink(0)
                wasi.stderr_custom = sink(1)
                wasi.preopen_dir(job["runtime_dir"], "/runtime", fs_mutable=False)
                wasi.preopen_dir(str(staged), "/skill", fs_mutable=False)
                store = wasmtime.Store(engine)
                store.set_limits(
                    memory_size=64 * 1024 * 1024,
                    table_elements=100000,
                    instances=1,
                    tables=1,
                    memories=1,
                )
                store.set_fuel(policy["fuel_per_case"])
                store.set_wasi(wasi)
                instance = linker.instantiate(store, module)
                exports = instance.exports(store)
                exit_code = 0
                try:
                    exports["_start"](store)
                except wasmtime.ExitTrap as exc:
                    exit_code = exc.code
                if overflow[0]:
                    raise ForgeError("WASI output exceeded the 64 KiB stream cap")
                stdout = buffers[0].decode("utf-8")
                stderr = buffers[1].decode("utf-8", errors="replace")
                if exit_code:
                    results.append(
                        {
                            "ok": False,
                            "error_type": "GuestExecutionError",
                            "exit_code": exit_code,
                            "stdout": redact(stdout[:4000]),
                            "stderr": redact(stderr[:4000]),
                        }
                    )
                    continue
                output = strict_json(stdout)
                Draft202012Validator(job["spec"]["outputs"]).validate(output)
                results.append(
                    {
                        "ok": True,
                        "output": output,
                        "exit_code": exit_code,
                        "fuel_used": policy["fuel_per_case"] - store.get_fuel(),
                        "memory_bytes": exports["memory"].data_len(store),
                        "seconds": time.monotonic() - started,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": redact(str(exc))[:2000],
                    }
                )
            finally:
                if store is not None:
                    store.close()
                if wasi is not None:
                    wasi.close()
            if len(json.dumps(results)) > 500000:
                raise ForgeError("WASI suite evidence exceeded its bounded size")
    return {"status": "completed", "results": results}


def main():
    try:
        job = strict_json(input_text := sys.stdin.read(5_000_001))
        if len(input_text) > 5_000_000:
            raise ForgeError("WASI worker request too large")
        limits = (
            linux_worker_limits(1024 * 1024 * 1024, job["timeout"]) if os.name != "nt" else None
        )
        report = execute(job)
        if limits:
            report["os_limits"] = limits
    except Exception as exc:
        report = {"status": "blocked", "results": [], "error": redact(str(exc))[:2000]}
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
