# CLI

All commands support `--help`. Global `--home PATH` precedes the command. Exit 0 is
success; 2 includes failure, refusal, rejected evolution and unverified generic tests.

| Command | Current behavior/options |
|---|---|
| `init [PATH]` | Local registry and legacy sample plan |
| `plan GOAL --output FILE` | Editable spec; `--kind text-cleaner/wasm-json/python-json`; optional `--contract FILE` |
| `build SPEC --output DIR` | Legacy deterministic build; `--bundle FILE` or model options for generic engineering |
| `test DIR --report FILE` | Static and actual isolated execution; generic `--evaluation FILE` required for verified status |
| `run DIR --input FILE` | JSON input/output; no host Python execution |
| `evolve DIR --output DIR` | Repair/optimize/regression; `--bundle` or model options for generic candidates |
| `compare BASE CANDIDATE --report FILE` | Fresh independent and baseline behavior comparison |
| `registry add DIR [--activate]` | Fresh evaluation and immutable registration; generic `--evaluation` supported |
| `registry list/show/export/rollback` | Local version metadata and verified snapshot recovery |
| `doctor` | Real contained WASM probe, tool availability and default live-request policy |
| `sandbox supervise --container-config FILE` | Independent durable-lease recovery loop; `--once` for one sweep |
| `sandbox status/reap --container-config FILE` | Check supervisor/leases or retry interrupted and expired cleanup |

Model options for plan/build/evolve:

- `--local-model http://127.0.0.1:PORT/v1/chat/completions`,
  `--approve-local-model`, zero-priced `--model-config`, and `--budget-account`:
  actual free local inference. See [local models](local-model.md).
- `budget create/status/history/reconcile`: durable lifetime budgets and explicit
  unknown-outcome accounting. Real local/paid calls both require a budget account.

- `--response FILE`: offline `{responses:[Responses-envelope,...]}` fixture.
- `--model-config FILE`: explicit model/rates/budgets; no automatic live model.
- `--model-receipts FILE`: mandatory new audit destination outside Skill artifacts.
- `plan --contract FILE`: seal explicit input/output schemas before model planning.
  Unspecified root schemas are inferred by the model; the editable plan requires review.
- `plan --review-plan`: opt into a second bounded free-local planning request.
  Both attempts are recorded; this is model self-review, not independent acceptance.
- `build/evolve --example-input FILE` (repeat at most three times): operator-reviewed
  public inputs without answers. Finite JSON, schema, size and sensitive-value checks
  run before inference. Requires an explicit model generator; examples never replace holdouts.
- `--approve-model-request` plus `--credential-env NAME`: both needed for a live
  request after user approval. Offline fixtures reject these credential options.

Test/compare/evolve/registry-add accept `--evaluation FILE`. Generic files contain
`contract_hash` and independently authored `cases`; they must live outside Skills.
Model requests do not receive this file. `--container-config FILE` selects exactly
`image` (approved local repo@sha256:digest), `socket` (local rootless Unix socket),
and `lease_dir` (private persistent operator-owned directory). Run and doctor also
support this config. The supervisor must run independently before guest execution.
Config files cannot grant extra capabilities.

Alternatively `--python-runtime-config FILE` (alias of `--container-config`) selects
exactly `backend: "python-wasi"`, `runtime_dir`, and `manifest_sha256`. This sealed
runtime executes Python inside WASM with read-only capabilities; no Docker or
supervisor is needed. See [Python/WASI](python-wasi.md). Container supervision
commands continue to require the gVisor lease policy.

Evolution has `--max-iterations`, `--seconds` and `--cost-usd`; live backend cap must
fit the evolution cap. Unknown requests keep reservations and stop rather than
blindly retrying. Every new candidate uses a separate immutable version directory.
