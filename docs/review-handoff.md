# Independent review handoff

This repository is a local CLI. Review this code and its real execution evidence;
do not infer hosted service or production qualification from passing unit tests.
No external reviewer verdict is claimed by this document.

## Concrete boundaries to review

| Boundary | Implementation and evidence |
|---|---|
| Guest code / host | `_worker.py`, `_wasi_worker.py`, `python_wasi.py`, `process_limits.py`; no-import WASM and read-only WASI hostile probes on actual Windows/Linux runners |
| Native Python container | `containers.py`, `leases.py`; pre-create durable names, attestation, independent lease recovery and refusal without supervisor; actual stable gVisor startup is blocked upstream |
| Local model / network | `local_model.py`; literal loopback only, no proxies/redirects/credential discovery, no model tools; actual official Qwen/llama.cpp provenance and inference records |
| Paid model / operator authorization | `cli.py`, `providers.py`; explicit approval, model/prices and named credential, persistent account validation before the selected read; paid path mocked only |
| Cost / crashes / concurrent callers | `billing.py`; integer units, transaction-before-transport, unknown holds, immutable scope caps and explicit one-time reconciliation; real process contention/crash tests |
| Generator / independent evaluator | `testing.py`, `evolution.py`; separate case namespaces, output contract and JSON-type checks, previous passing behavior and holdout hash, filtered model feedback and bounded previous source |
| Artifact / version state | `artifacts.py`, `validation.py`, `registry.py`; paths/links/device aliases, immutable snapshots, activation CAS and rollback checks |

## Reviewer decisions that remain external

Evaluate native engine/JIT and OS assumptions; assess state directory ownership and
Windows inherited ACL expectations; examine model server exposure and supply chain;
review provider accounting/price assumptions and unknown reconciliation authority;
review temporal/crash/concurrent invariants and attacks beyond the included probes.

The independent reviewer should provide findings tied to source revision, severity,
reproducer and disposition. Automated dependency/static scanner output is included
as supporting evidence, including retained low/medium findings and their triage.
It does not substitute for that verdict. No security protections should be disabled
to make a test environment appear supported.
