# AgentForge

**Local Skill engineering CLI.** Python 3.11+, MIT. Development version: `0.2.0a4`.
[Public Alpha downloads](https://github.com/zyf628768-cmyk/agentforge/releases) ·
[CI evidence](https://github.com/zyf628768-cmyk/agentforge/actions).
[中文](README.zh-CN.md) · [readiness](docs/production-readiness.md)

AgentForge turns a goal and editable JSON contract into a complete Skill project,
tests executable artifacts, evaluates repair candidates, rejects regressions and
preserves immutable SQLite/Git version history. It runs locally by default.

This iteration adds provider-neutral engineering bundles, an OpenAI Responses
backend, generic WASM/JSON execution, sealed CPython/WASI and a fail-closed Python container adapter.
It accepts arbitrary implementation code for supported compute-only contracts;
it is not a switch which maps every goal to the old text-cleaner template.
The Alpha is publicly released. All ten Windows/Linux and Python 3.11–3.15 CI jobs
and the corresponding ten fresh offline installation jobs passed.
No paid model requests or real credential inspection are part of offline development.
An explicitly approved [free local model backend](docs/local-model.md) performs
actual llama.cpp inference. [Shared durable budgets](docs/budgets.md) preserve
request/token/money limits across processes and restarts; unknown charges remain held.
Authored protocol fixtures remain labelled. Actual free 14B local inference now
has accepted artifacts across eight domains: seven unassisted and CSV with public
input-only assistance. All accepted artifacts passed 410 distinct fresh independent
cases. Failures, actual model repair and regression rejection are retained.
See [measured results](docs/actual-local-results.md) and release RESULTS files.
The user reported human review passed; [attestation provenance](docs/human-review-attestation.json)
does not invent a reviewer, report or covered revision.

## Install

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
python -m pip install -e '.[dev]'
agentforge doctor
```

Windows workers use a verified Job Object with a 256 MiB aggregate committed-memory
cap, finite CPU time, two-process limit (venv launcher + interpreter), kill-on-close
and an external wall watchdog. Guest WASM has no imports/WASI and one 64 KiB memory.
Linux trusted-worker rlimits are exercised in CI; guest escape resistance is a
separate security qualification claim.

## Generic Skill engineering, entirely offline

```sh
agentforge plan 'Compute sum and count of signed integers' --name integer-stats --kind wasm-json --response examples/v02/integer-stats.planning-response.json --model-receipts planning-receipts.json --output plan.json
# Human-review/edit the plan before building.
agentforge build plan.json --response examples/v02/integer-stats.response.json --model-receipts build-receipts.json --output skills/integer-stats
agentforge test skills/integer-stats --evaluation examples/v02/integer-stats.evaluation.json --report numeric-test.json
agentforge run skills/integer-stats --input skills/integer-stats/examples/input.json
```

The numeric Skill returns `{"sum":6,"count":3}`. A separate ROT13 implementation
preserves Unicode and JSON escapes. A Python CSV-column summary project is also
generated and executes in an explicitly selected CPython/WASI runtime. Real tests
cover CSV repair, rejected regressions and denied guest capabilities. See
[Python/WASI setup](docs/python-wasi.md). No generated Python is run on the host. See
[sandbox operations](docs/sandbox-operations.md) for crash recovery and real
gVisor qualification commands and evidence requirements. The strict native profile
uses an exact upstream rootless fix and a recorded errno patch with matching
sidecars and unit tests. Its upstream PR remains open; see
[pinned runtime](docs/pinned-gvisor.md) and release containment results.

`--bundle FILE` accepts the same engineering format from another generator without
using a model. A bundle contains real source (`scripts/main.wat` or `main.py`),
README, behavioral test cases and example JSON. Identity, schemas, executable hashes,
runtime metadata and SKILL.md are sealed by the trusted builder. Paths, sizes,
case aliases, Windows devices, schema complexity and likely secrets are checked.
Untrusted WAT compilation occurs only in a contained worker.

## Independent acceptance and repair

Generic Skills require a separately held evaluation file bound to the input/output
contract hash. Without it, passing generated tests yields `unverified`, not a
verified registry version. Model requests do not contain independent cases.
Only generated-case failures are provided as repair feedback. Previously passing
baseline behavior is revalidated, including cases deleted by the candidate.

```sh
agentforge build examples/v02/integer-stats.plan.json --bundle examples/v02/integer-stats.broken.bundle.json --output broken/integer-stats
agentforge evolve broken/integer-stats --response examples/v02/integer-stats.response.json --model-receipts repair-receipts.json --evaluation examples/v02/integer-stats.evaluation.json --output repair --seconds 30 --max-iterations 2 --cost-usd 0
agentforge registry add skills/integer-stats --evaluation examples/v02/integer-stats.evaluation.json --activate
agentforge registry list
```

Candidates remain in separate directories. Activation checks the expected active
version atomically; a concurrent change refuses promotion. Existing artifacts,
audit files and accepted snapshots are not overwritten.

## Real model backend

The Responses HTTP adapter implements strict structured output, refusal/incomplete
response handling, bounded reads, disabled redirects/proxy inheritance, token/cost
reservations and audit receipts. Model id and reviewed prices must be explicit.
Unknown outcomes retain the reservation; no request is automatically retried.

**Live requests remain disabled by default.** They require reviewed model config,
a positive cap/prices, `--approve-model-request`, an explicitly chosen
`--credential-env`, and a new audit destination. No credentials are automatically
discovered. The paid-provider path uses offline fixtures and mocked HTTP tests;
actual free local inference is recorded separately. Paid-provider quality and
billing remain untested pending specific approval.
See [model backend](docs/model-backend.md).

## Verification and remaining work

```sh
python -m pytest -q
ruff check src tests tools
python tools/verify_v02.py --output offline-evidence
```

Every CLI command provides `--help`. Original v0.1.0 text-cleaner workflows remain
supported. The original ZIP/tag are preserved. See [CLI](docs/cli.md),
[security](docs/security.md), [architecture](docs/architecture.md) and
[qualification scope](docs/production-readiness.md). No web service is shipped.
