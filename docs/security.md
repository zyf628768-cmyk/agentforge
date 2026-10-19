# Security model — 0.2.0a4

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
before compiling a guest, with reduced Wasmtime memory reservation. Actual Ubuntu
CI exercises the worker and reports its limits. Unsupported OS or failed
containment refuses execution. Native-engine vulnerabilities remain in the TCB.

Modules <=100 KB, <=128 cases, requests <=250 KB, input/output <=32 KiB per call;
files/directories and bundle sizes are bounded. WASM and schema validation use
wall/fuel/resource limits. Schemas disallow references, regex and expensive
composition features; strict JSON forbids NaN/Infinity. Boolean true cannot pass
an expected numeric one. Negative-input cases must actually violate input schema.

## Python container adapter

An independent explicitly selected [CPython/WASI backend](python-wasi.md) also
executes pure-compute Python on Windows/Linux. It exposes only read-only approved
runtime/scripts and bounded JSON streams, never native generated host Python.
Its 64 MiB guest and 512 MiB Windows / 1 GiB Linux worker limits are separate from
the smaller no-import WASM limits above. Linux workers install parent-death SIGKILL;
actual kernel termination is covered by a Linux-only test.

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

Container names and durable SQLite leases are recorded before create. A separate
supervisor inventories only its policy and matching leased identities, removes
expired or interrupted containers, and retries cleanup after daemon recovery.
Tombstones catch late create responses. New executions require a fresh heartbeat;
the supervisor must itself be managed by a restarting service manager. Created
entrypoint, arguments, labels, tmpfs, ulimits, restart/logging and auxiliary device
settings are also attested. See [operations](sandbox-operations.md).

The Windows development host cannot run gVisor guests. The separate Linux runner
uses an exact upstream rootless fix plus a versioned systrap resource-errno patch.
Source, patch, both Go unit suites and matching binary hashes are recorded. Earlier
startup and hostile-probe failures remain in the evidence; no controls are disabled.
See [pinned runtime](pinned-gvisor.md) and the release's actual qualification results.
The dedicated actual-gVisor workflow is the evidence source. Mocked daemon tests alone
never establish real escape resistance. OS/daemon outages suspend cleanup until
recovery; a lease is not a guaranteed hard TTL during those outages.
See [gVisor rootless](https://gvisor.dev/docs/user_guide/rootless/) and
[Docker create flags](https://docs.docker.com/reference/cli/docker/container/create/).

## Model, artifacts and storage

Live API requests require explicit approval, selected credential variable, reviewed
model/prices and bounded budget. No discovery or actual secret reads occurred in
this offline development run. Receipts exclude keys and preserve metering fields;
redaction also applies to SQLite evidence. Redaction remains best effort.

Actual free local inference is explicitly selected by literal loopback HTTP with no
proxy, redirects or provider credential discovery. The server is trusted operator
software with no model tool execution. Real inference reserves an initialized
durable budget before transport. Hard exit leaves the hold in SQLite; operator
reconciliation records receipt hashes and redacted notes. See [budgets](budgets.md),
[local models](local-model.md) and [scanner review](security-review.md). Scanner
findings are retained and do not replace an independent human audit.

Paths, aliases, devices, links, metadata overrides and nested writes into existing
Skills are rejected. Generated scripts are statically parsed. Candidate fixtures
do not define independent acceptance; missing independent cases yields unverified.
Version activation uses SQLite compare-and-swap after tests. Local Git hooks/global
configuration are disabled for snapshots, and prior versions stay immutable.
Local owners who can rewrite both code and databases are outside this trust model.
