# Production readiness — 0.2.0a3

Status: **public CLI Alpha; offline isolation and recovery implemented**. Paid model testing is
explicitly excluded from this development round. An independent security review
cannot be replaced by the project's own automated checks.

| Area | Implemented | Validation status / remaining gate |
|---|---|---|
| General goal/spec | Editable generic JSON contracts and model-assisted planning | Offline Responses fixtures; not arbitrary-goal model quality |
| General source generation | Provider-neutral code bundles, WASM JSON ABI and Python JSON target | Numeric/ROT13 WASM and CSV Python actually execute; generic code bundle interface |
| Real model adapters | OpenAI Responses plus literal-loopback llama.cpp and typed local engineering | Actual free local inference recorded separately; paid-provider HTTP remains mocked |
| Durable inference budgets | Atomic money/token/request holds, persistent unknown outcomes and explicit reconciliation | Real cross-process contention and hard-exit tests; not a provider-wide billing cap |
| Broader independent domains | Invoice totals, interval union, Unicode casefold histogram | Authored deterministic artifacts execute against independent oracles; model results reported separately |
| Repair/evolution | Generic generator injection, filtered feedback, baseline/independent gates and CAS activation | Real numeric defect repair and regression rejection offline |
| WASM isolation | No imports/WASI, bounded memory/fuel/stack, contained compilation | Real guest tests and Windows OS quota probes |
| Windows OS quotas | Job committed-memory, process count, CPU user-time and kill-on-close | Actual allocation denial and process-tree timeout probes |
| Linux OS quotas | RLIMIT_AS/CPU/NOFILE/CORE with reduced WASM reservation | Actual Ubuntu CI execution; native-engine review remains separate |
| Python/WASI isolation | Pinned official CPython runtime, manifest hashes, read-only preopens, no inherited environment/network/processes, quotas | Actual Windows CSV repair/regression and hostile probes pass; cross-platform workflow records results |
| Python/gVisor isolation | Explicit local rootless socket, immutable image, cgroups and pre-start inspection | Actual Ubuntu run blocked by upstream rootless/systemd defect; [failure evidence](https://github.com/zyf628768-cmyk/agentforge/actions/runs/39261545029), [upstream fix](https://github.com/google/gvisor/pull/13853); no ignore-cgroups workaround |
| Credential boundary | No automatic discovery; explicit selected read only behind live gates | Offline approval-gate tests; no real key read |
| Version/storage | Immutable snapshots, redacted evidence at rest, atomic active-version CAS | Local SQLite/Git tests |
| Crash recovery | Pre-create SQLite leases, independent supervisor, clock/boot expiry, late-create tombstones and retryable cleanup | Local persistence/failure tests; actual gVisor workflow required |
| Cross-platform CI | Windows/Linux and Python 3.11–3.13 | [Six successful hardening jobs](https://github.com/zyf628768-cmyk/agentforge/actions/runs/39263848349); Linux parent-death probe executes |

Before production:

1. Approve an exact model, key reuse/new-key choice and spend cap, then perform a
   real-model quality/cost/latency acceptance set across several domains. Model
   protocol fixtures do not establish synthesis quality. Prices in config must be
   reviewed. Shared durable reservations now span processes/restarts using the same
   home/account; they are not a provider-enforced account billing cap.
2. Resolve the reviewed upstream gVisor rootless/systemd cgroup defect before
   container qualification. The dedicated runner was provisioned and actual
   qualification attempted; startup failed before guest execution. Retain that
   failure evidence. Re-run hostile and crash probes after an approved runtime
   fix; do not disable cgroups. Compute-only Python can explicitly use the tested
   [CPython/WASI backend](python-wasi.md) with its stated compatibility limits.
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
