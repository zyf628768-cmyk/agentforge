# Architecture

`spec.py` supports legacy text-cleaning and generic wasm-json/python-json plans.
`contracts.py` validates a bounded local JSON Schema subset, test-case semantics
and sealed contract hashes. Goal/steps are data, never host shell instructions.

`providers.py` implements Responses request/response handling, injectable offline
transport, explicit live gates, conservative budget reservations and audit receipts.
`ModelGenerator` accepts arbitrary supported-target source from the provider.
`artifacts.py` validates file bundles and stages complete projects atomically; the
trusted builder seals identities, schemas, hashes, runtime metadata and SKILL.md.
`generator.py` retains the deterministic v0.1 text compiler for regression coverage.

`process_limits.py` resource-contains the trusted worker before payload delivery.
`sandbox.py` invokes `_worker.py`, which compiles and executes no-import WASM.
`containers.py` stages Python only for a qualified local rootless gVisor daemon,
attests created-container controls before start and bounds IO/time/resources.
Container lifecycle failure recovery remains a production qualification item.

`testing.py` evaluates generated, external independent and prior baseline cases.
Generic generated-only results are unverified. Independent files are bound to the
contract and remain outside the candidate. `evolution.py` injects either a bundle
or model generator, sends only generated failures as feedback, evaluates new
versions and compares gates under budgets. Model failures/reservations are logged.

`registry.py` stores redacted reports and immutable bytes in SQLite plus separate
local Git snapshots. Active-version compare-and-swap prevents stale evaluations
overwriting a changed pointer. Rollback/export verify snapshot consistency.

No web server, secret provisioning, real-model invocation, public push or automatic
dependency installation is part of this iteration's offline validation.
