# Python Skills in CPython/WASI

`python-json` Skills can explicitly select a sealed CPython 3.13 WebAssembly runtime.
The Python source runs inside Wasmtime, including parsing and imports. A subprocess
only hosts this engine; native host Python never interprets generated source.
There is no automatic fallback between this backend and gVisor.

This runtime supports compute-only Python/stdlib programs, including CSV, JSON and
statistics. It does not promise native wheels, GUI, subprocesses, writable files,
network services or all CPython platform modules. Arbitrary-goal model quality is
not established by these deterministic examples.

## Provision once, run offline

On a dedicated Linux build VM, run `python tools/ci/build_python_wasi.py --output
python-wasi-runtime`. This explicit provisioning downloads official pinned CPython,
WASI SDK and Wasmtime CLI sources/tools, verifies GitHub release asset SHA-256 and
records build commands and exit codes. It is never invoked by Skill execution.
The resulting directory is portable to supported Windows/Linux Wasmtime hosts.
Keep the included CPython license and provenance manifest.

Review the manifest, compute its SHA-256 independently, and keep the runtime outside
Skill directories. Create an operator-owned config (replace the example values):

```json
{
  "backend": "python-wasi",
  "runtime_dir": "/absolute/path/python-wasi-runtime",
  "manifest_sha256": "<reviewed 64-character SHA-256>"
}
```

Windows paths use JSON escapes, e.g. `C:\\AgentForge\\python-wasi-runtime`.
Every invocation verifies the manifest hash, exact file set and every file hash,
and refuses links/junctions. Runtime files are trusted operator inputs: another
process with operator write privileges must not modify them during execution.

```sh
agentforge build examples/v02/csv-summary.plan.json --bundle examples/v02/csv-summary.bundle.json --output skills/csv-summary
agentforge test skills/csv-summary --evaluation examples/v02/csv-summary.evaluation.json --python-runtime-config wasi-policy.json --report csv-report.json
agentforge run skills/csv-summary --input skills/csv-summary/examples/input.json --python-runtime-config wasi-policy.json
python tools/qualify_wasi.py --runtime-dir python-wasi-runtime --manifest-sha256 REVIEWED_HASH --output new-qualification
```

The CSV example returns `{"count":2,"sum":6.0,"mean":3.0}`. The qualification script
actually repairs an injected sum defect, rejects a regressing candidate, checks the
active version hash, and runs hostile guests. It never calls a paid model.

## Enforced capabilities and budgets

- Only WASI preview1 host imports; only `/runtime` and `/skill` preopened read-only.
  `/skill` contains copied scripts, without evaluator files or registry data.
- No inherited host environment, sockets, process spawning or native extensions.
  The guest gets only `LANG=C.UTF-8`, JSON stdin, and bounded stdout/stderr.
- 64 MiB guest linear memory, 1 MiB WASM stack and 5 billion fuel per case; this
  includes CPython startup and stdlib parsing. Each case gets fresh memory/state.
- 32 KiB JSON input, 64 KiB per output stream, bounded aggregate evidence, and a
  finite whole-worker wall timeout (normally 15 seconds; hard maximum 30).
- Serial JIT compilation; Windows Job Object aggregate committed memory 512 MiB,
  CPU quota and kill-on-close; Linux address-space limit 1 GiB, CPU/no-file/core
  limits and kernel parent-death SIGKILL. These host quotas supplement WASM.

Fuel does not interrupt a sleeping WASI host call; the external wall watchdog and
parent-death mechanism handle that case. Wasmtime and CPython remain trusted
dependencies. Automated probes are evidence, not an independent security audit.

## gVisor status

The separate rootless gVisor path retains strict cgroup enforcement and supervised
leases. Actual qualification found upstream rootless/systemd startup failure:
`Interactive authentication required`. See [upstream fix under review](https://github.com/google/gvisor/pull/13853)
and [actual failed CI](https://github.com/zyf628768-cmyk/agentforge/actions/runs/39261545029).
The project does not enable `--ignore-cgroups`, switch to rootful Docker, or claim
that container hostile-code/crash probes passed when the runtime could not start.
The gVisor workflow is manual until a reviewed upstream fix is available.
