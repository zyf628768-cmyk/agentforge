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

Model options for plan/build/evolve:

- `--response FILE`: offline `{responses:[Responses-envelope,...]}` fixture.
- `--model-config FILE`: explicit model/rates/budgets; no automatic live model.
- `--model-receipts FILE`: mandatory new audit destination outside Skill artifacts.
- `--approve-model-request` plus `--credential-env NAME`: both needed for a live
  request after user approval. Offline fixtures reject these credential options.

Test/compare/evolve/registry-add accept `--evaluation FILE`. Generic files contain
`contract_hash` and independently authored `cases`; they must live outside Skills.
Model requests do not receive this file. `--container-config FILE` selects exactly
`image` (approved local repo@sha256:digest) and `socket` (local rootless Unix socket).
Run also supports this container config. Config files cannot grant extra capabilities.

Evolution has `--max-iterations`, `--seconds` and `--cost-usd`; live backend cap must
fit the evolution cap. Unknown requests keep reservations and stop rather than
blindly retrying. Every new candidate uses a separate immutable version directory.
