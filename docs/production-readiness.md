# Release qualification — 0.2.0a4

AgentForge is a local Skill engineering CLI. The supported release profile is
compute-only JSON Skills, independently evaluated before activation. The release
RESULTS files are the source of exact commands, revisions, outcomes and CI links.

| Area | Implemented and exercised | Scope |
|---|---|---|
| Planning | Editable specifications, real local structured planning, explicit contract seals, optional bounded free-local self-review | A valid schema alone does not prove the goal was understood; review the plan |
| Generation | Provider-neutral runnable bundles, WASM/JSON and Python/JSON; actual 14B inference across eight domains | Seven unassisted, CSV input-assisted; initial failures retained |
| Independent quality | 410 distinct independent fresh-seed cases, 458 executed checks across accepted artifacts | Recorded task distribution, not arbitrary goals |
| Repair/evolution | Real model repair, baseline comparison, independent gates, rejection and immutable activation | Finite request/time/token/money budgets |
| Storage | SQLite metadata, hash-bound snapshots, Git rollback, activation CAS | Local trusted state ownership |
| WASM | No imports/WASI, bounded memory/fuel/stack, contained compilation | Actual Windows/Linux worker quotas |
| Python/WASI | Pinned CPython, verified manifest, read-only preopens, no inherited environment/network/processes | Explicit compatibility limits |
| Python/gVisor | Pinned rootless upstream fix plus a recorded errno patch; cgroup v2, seccomp, immutable image, nonroot UID, read-only mounts, resource limits | Only the exact tested Linux profile; upstream PR remains open |
| Crash recovery | Independent durable lease supervisor, caller/daemon/supervisor recovery, retryable cleanup | An unavailable host/daemon is not a hardware wall-clock TTL |
| Distribution | Windows/Linux Python 3.11–3.15 test matrix and ten native offline wheelhouses | Fresh no-index installs and real CLI/demonstration records |
| Review | User reported human review passed; provenance recorded | Reviewer/report/covered SHA were not supplied; no invented coverage of later changes |

The Responses paid-provider adapter is implemented and tested with recorded and
mocked HTTP responses. Live paid-provider quality, latency and billing are outside
this authorized round. No keys were discovered or paid calls made. Persistent
engine budgets are not a provider-enforced account-wide billing cap.

The pinned gVisor source is an open upstream change, not an upstream stable release.
Its exact source, patch, unit tests, binary hashes and hostile runtime evidence are
shipped separately. Do not substitute unrelated runtimes or disable controls.
`doctor` reports local prerequisites and refuses unsupported isolation; it does
not confer universal production certification (`production_qualified` stays false).

No hosted service is shipped. A future multi-tenant service needs its own identity,
tenant boundaries, backup/incident operations and deployment review. Public source
publication does not deploy a production service or publish generated Skills.
