"""Trusted worker. The guest gets no imports (in particular, no WASI)."""

from __future__ import annotations

import base64
import json
import os
import sys
import time

import wasmtime
from jsonschema import Draft202012Validator

from .contracts import check_schema
from .core import redact, strict_json
from .process_limits import linux_worker_limits
from .spec import INPUT_SCHEMA, OUTPUT_SCHEMA


def execute(job: dict) -> dict:
    config = wasmtime.Config()
    config.consume_fuel = True
    config.wasm_threads = False
    config.wasm_memory64 = False
    config.wasm_multi_memory = False
    config.max_wasm_stack = 128 * 1024
    if os.name != "nt":
        config.memory_reservation = 65536
        config.memory_guard_size = 65536
    engine = wasmtime.Engine(config)
    binary = (
        bytes(wasmtime.wat2wasm(job["wat"]))
        if job.get("wat") is not None
        else base64.b64decode(job["wasm"], validate=True)
    )
    if len(binary) > 100_000:
        raise ValueError("Module size limit exceeded")
    module = wasmtime.Module(engine, binary)
    if module.imports:
        raise ValueError("All guest imports are forbidden; WASI is not linked")
    if job.get("wat") is not None:
        exported = {entry.name: entry.type for entry in module.exports}
        signature = exported.get("run")
        if (
            not isinstance(exported.get("memory"), wasmtime.MemoryType)
            or not isinstance(signature, wasmtime.FuncType)
            or [str(v) for v in signature.params] != ["i32"]
            or [str(v) for v in signature.results] != ["i32"]
        ):
            raise ValueError("Generic WASM requires memory and run(i32)->i32 exports")
        return {
            "status": "completed",
            "results": [],
            "compiled_wasm": base64.b64encode(binary).decode(),
        }
    contract = job.get("contract")
    input_schema = contract["inputs"] if contract else INPUT_SCHEMA
    output_schema = contract["outputs"] if contract else OUTPUT_SCHEMA
    check_schema(input_schema)
    check_schema(output_schema)
    results = []
    for value in job["inputs"]:
        started = time.monotonic()
        try:
            Draft202012Validator(input_schema).validate(value)
            raw = (
                json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
                if contract
                else value["text"].encode("utf-8")
            )
            if len(raw) > 32768:
                raise ValueError("UTF-8 input exceeds 32768 bytes")
            store = wasmtime.Store(engine)
            store.set_limits(memory_size=65536, table_elements=0, instances=1, tables=0, memories=1)
            store.set_fuel(job["fuel"])
            instance = wasmtime.Instance(store, module, [])
            exports = instance.exports(store)
            memory = exports["memory"]
            clean = exports["run" if contract else "clean"]
            if not isinstance(memory, wasmtime.Memory) or not isinstance(clean, wasmtime.Func):
                raise ValueError("WASM ABI mismatch")
            signature = clean.type(store)
            if [str(v) for v in signature.params] != ["i32"] or [
                str(v) for v in signature.results
            ] != ["i32"]:
                raise ValueError("WASM function ABI must be i32->i32")
            memory.write(store, raw, 0)
            length = clean(store, len(raw))
            if type(length) is not int or not 0 <= length <= 32768:
                raise ValueError("WASM output outside ABI bounds")
            decoded = bytes(memory.read(store, 32768, 32768 + length)).decode("utf-8")
            output = strict_json(decoded) if contract else {"text": decoded}
            Draft202012Validator(output_schema).validate(output)
            results.append(
                {
                    "ok": True,
                    "output": output,
                    "fuel_used": job["fuel"] - store.get_fuel(),
                    "memory_bytes": memory.data_len(store),
                    "seconds": time.monotonic() - started,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": redact(str(exc))[:2000],
                    "seconds": time.monotonic() - started,
                }
            )
    return {"status": "completed", "results": results}


def main() -> int:
    try:
        job = strict_json(sys.stdin.read(250_001))
        os_limits = (
            linux_worker_limits(1024 * 1024 * 1024, job.get("cpu_seconds", 5))
            if os.name != "nt"
            else None
        )
        report = execute(job)
        if os_limits:
            report["os_limits"] = os_limits
    except Exception as exc:
        report = {"status": "blocked", "error": redact(str(exc))[:2000], "results": []}
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
