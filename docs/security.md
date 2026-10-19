# Security model — 0.2.0a1

Untrusted: generated code/files, provider responses, candidate cases, goals and
input JSON. Trusted: installed AgentForge/Python, Wasmtime/JIT, OS, selected local
container runtime and approved image/operator. No arbitrary generated Python is
run in a host process. A venv, child process or Job Object alone is not a sandbox.

## WASM code boundary and resource containment

Guest imports are rejected before instantiation. No WASI, host functions, sockets,
filesystem or environment interfaces are linked. Threads, memory64 and multi-memory
are disabled. Stores permit one instance, one 64 KiB memory and zero tables with
bounded stack/fuel. JSON ABI: input bytes at 0, output at 32768; `run(i32)->i32`.
Output length, strict JSON and output schema are checked. Legacy text ABI is kept.
Model WAT compilation happens inside the same contained trusted worker.

Windows parent creates/configures/reads back a Job Object and assigns the trusted
worker before sending any guest payload. Default job and per-process committed
memory caps are 256 MiB; active processes are limited to two for the Windows venv
launcher plus real interpreter, with no breakaway. Finite user CPU time and
kill-on-close are enabled. On timeout, the Job is closed before waiting on pipes,
so the interpreter descendant is terminated too. Actual probes use an authored
trusted helper to show 128 MiB allocation is refused under a 64 MiB job limit.
These are committed-memory limits, not exact RSS measurements.
See [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Linux trusted worker sets finite address-space/CPU/core/file-descriptor limits
before compiling a guest, with reduced Wasmtime memory reservation. This code has
not been physically qualified on this Windows host. Unsupported OS or failed
containment refuses execution. Native-engine vulnerabilities remain in the TCB.

Modules <=100 KB, <=128 cases, requests <=250 KB, input/output <=32 KiB per call;
files/directories and bundle sizes are bounded. WASM and schema validation use
wall/fuel/resource limits. Schemas disallow references, regex and expensive
composition features; strict JSON forbids NaN/Infinity. Boolean true cannot pass
an expected numeric one. Negative-input cases must actually violate input schema.

## Python container adapter

Only an explicitly selected local rootless Unix socket is eligible. Remote Docker
contexts and inherited DOCKER_HOST/config/registry credentials are not used.
Preflight requires Linux, rootless, cgroup v2, resource support, seccomp and runsc.
An immutable approved digest must already be local; no pull/build/install occurs.
Image credentials/unapproved env and declared writable volumes are rejected.

The adapter requests gVisor, no network, read-only root and source mount, dropped
capabilities, no-new-privileges, nonroot UID, memory/CPU/PID/ulimit limits, bounded
tmpfs, no healthcheck and no persistent log driver. Created-container settings are
read back before start; unexpected resources, privileges or mounts refuse execution.
Only generated scripts are staged; no host home, credentials, sockets or evaluator
corpus are mounted. Streams are capped and execution uses a wall watchdog.

All containers are removed in finally. Daemon/CLI/host failure can interrupt cleanup;
a qualified durable reaper/lease is still required for production. The current host
has no qualified runtime, so actual Python execution is blocked. Mocked daemon tests
are protocol/policy tests, not proof of real container escape resistance.
See [gVisor rootless](https://gvisor.dev/docs/user_guide/rootless/) and
[Docker create flags](https://docs.docker.com/reference/cli/docker/container/create/).

## Model, artifacts and storage

Live API requests require explicit approval, selected credential variable, reviewed
model/prices and bounded budget. No discovery or actual secret reads occurred in
this offline development run. Receipts exclude keys and preserve metering fields;
redaction also applies to SQLite evidence. Redaction remains best effort.

Paths, aliases, devices, links, metadata overrides and nested writes into existing
Skills are rejected. Generated scripts are statically parsed. Candidate fixtures
do not define independent acceptance; missing independent cases yields unverified.
Version activation uses SQLite compare-and-swap after tests. Local Git hooks/global
configuration are disabled for snapshots, and prior versions stay immutable.
Local owners who can rewrite both code and databases are outside this trust model.
