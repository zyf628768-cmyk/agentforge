# Production readiness — 0.2.0a1

Status: **offline engineering milestone; production qualification incomplete**.

| Area | Implemented | Validation status / remaining gate |
|---|---|---|
| General goal/spec | Editable generic JSON contracts and model-assisted planning | Offline Responses fixtures; not arbitrary-goal model quality |
| General source generation | Provider-neutral code bundles, WASM JSON ABI and Python JSON target | Numeric and ROT13 WASM execute; Python project statically checked |
| Real model adapter | OpenAI Responses HTTP path, strict output, refusals, usage and budgets | HTTP mocked and protocol fixtures only; no live calls |
| Repair/evolution | Generic generator injection, filtered feedback, baseline/independent gates and CAS activation | Real numeric defect repair and regression rejection offline |
| WASM isolation | No imports/WASI, bounded memory/fuel/stack, contained compilation | Real guest tests and Windows OS quota probes |
| Windows OS quotas | Job committed-memory, process count, CPU user-time and kill-on-close | Actual allocation denial and process-tree timeout probes |
| Linux OS quotas | RLIMIT_AS/CPU/NOFILE/CORE with reduced WASM reservation | Code present; not physically verified on this Windows host |
| Python isolation | Explicit local rootless socket, gVisor, immutable image, cgroup limits and pre-start inspection | Mocked daemon contract/refusal tests; actual environment absent |
| Credential boundary | No automatic discovery; explicit selected read only behind live gates | Offline approval-gate tests; no real key read |
| Version/storage | Immutable snapshots, redacted evidence at rest, atomic active-version CAS | Local SQLite/Git tests |

Before production:

1. Approve an exact model, key reuse/new-key choice and spend cap, then perform a
   real-model quality/cost/latency acceptance set across several domains. Model
   protocol fixtures do not establish synthesis quality. Prices in config must be
   reviewed; reservations are per backend invocation, not an account billing cap.
2. Provision a dedicated non-production Linux runner and approved image/runsc
   configuration. Execute hostile-Python filesystem/network/fork/memory/output
   and timeout tests against the actual container stack. Do not weaken preflight
   to make an unavailable environment look supported.
3. Qualify crash recovery and a durable external container reaper/lease mechanism.
   The adapter removes containers in finally, but CLI/daemon/host failure can defeat
   that cleanup; this is a production blocker, not a guaranteed hard container TTL.
4. Run the cross-platform CI matrix. Linux and other Python versions configured in
   CI are not claimed as executed locally. Have an independent reviewer assess the
   native engine, protocol boundaries and container policy.
5. Define deployment topology, authentication, tenant isolation, persistent billing
   limits, concurrent service operations, backups, telemetry and incident handling
   if a web/API service is desired. The product shipped here is a local CLI.

The public Alpha release does not establish production qualification or authorize
paid model calls or production deployment. The v0.1.0 tag/archive remain unchanged.
