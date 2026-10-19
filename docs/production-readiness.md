# Production readiness — 0.2.0a2

Status: **public CLI Alpha; offline hardening in progress**. Paid model testing is
explicitly excluded from this development round. An independent security review
cannot be replaced by the project's own automated checks.

| Area | Implemented | Validation status / remaining gate |
|---|---|---|
| General goal/spec | Editable generic JSON contracts and model-assisted planning | Offline Responses fixtures; not arbitrary-goal model quality |
| General source generation | Provider-neutral code bundles, WASM JSON ABI and Python JSON target | Numeric and ROT13 WASM execute; Python project statically checked |
| Real model adapter | OpenAI Responses HTTP path, strict output, refusals, usage and budgets | HTTP mocked and protocol fixtures only; no live calls |
| Repair/evolution | Generic generator injection, filtered feedback, baseline/independent gates and CAS activation | Real numeric defect repair and regression rejection offline |
| WASM isolation | No imports/WASI, bounded memory/fuel/stack, contained compilation | Real guest tests and Windows OS quota probes |
| Windows OS quotas | Job committed-memory, process count, CPU user-time and kill-on-close | Actual allocation denial and process-tree timeout probes |
| Linux OS quotas | RLIMIT_AS/CPU/NOFILE/CORE with reduced WASM reservation | Actual Ubuntu CI execution; native-engine review remains separate |
| Python isolation | Explicit local rootless socket, gVisor, immutable image, cgroup limits and pre-start inspection | Mocked daemon contract/refusal tests; actual environment absent |
| Credential boundary | No automatic discovery; explicit selected read only behind live gates | Offline approval-gate tests; no real key read |
| Version/storage | Immutable snapshots, redacted evidence at rest, atomic active-version CAS | Local SQLite/Git tests |
| Crash recovery | Pre-create SQLite leases, independent supervisor, clock/boot expiry, late-create tombstones and retryable cleanup | Local persistence/failure tests; actual gVisor workflow required |
| Cross-platform CI | Windows/Linux and Python 3.11–3.13 | [Six successful Alpha jobs](https://github.com/zyf628768-cmyk/agentforge/actions/runs/39257831996); hardening branch re-runs the matrix |

Before production:

1. Approve an exact model, key reuse/new-key choice and spend cap, then perform a
   real-model quality/cost/latency acceptance set across several domains. Model
   protocol fixtures do not establish synthesis quality. Prices in config must be
   reviewed; reservations are per backend invocation, not an account billing cap.
2. Provision a dedicated non-production Linux runner and approved image/runsc
   configuration. Execute hostile-Python filesystem/network/fork/memory/output
   and timeout tests against the actual container stack. Do not weaken preflight
   to make an unavailable environment look supported.
3. Operate the implemented independent lease supervisor under a restarting service
   manager with durable state. Run actual crash/daemon recovery probes; daemon or
   host outages are never claimed to have a hardware-enforced wall TTL. See
   [sandbox operations](sandbox-operations.md).
4. Keep the cross-platform matrix green for changes. The Alpha matrix already ran
   successfully on six actual runners; this is no longer an unexecuted checklist
   item. Have an independent reviewer assess the native engine, protocol boundaries
   and container policy.
5. Define deployment topology, authentication, tenant isolation, persistent billing
   limits, concurrent service operations, backups, telemetry and incident handling
   if a web/API service is desired. The product shipped here is a local CLI.

The public Alpha release does not establish production qualification or authorize
paid model calls or production deployment. The v0.1.0 tag/archive remain unchanged.
