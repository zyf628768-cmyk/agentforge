# Free local model inference

The loopback llama.cpp backend performs actual inference, labelled
`local-llama.cpp` with `offline_fixture: false`. Authored protocol data remains
labelled as fixtures. No provider credentials are discovered or needed.

Provision trusted official binaries and a reviewed GGUF separately; record immutable
revisions, SHA-256, source URLs and licenses. The local acceptance uses official
Qwen/Qwen2.5-Coder-{3B,7B,14B}-Instruct-GGUF Q4_K_M,
with llama.cpp b11669. [Actual results and failures](actual-local-results.md) are
distinct from offline fixtures. Provisioning downloads
free software/models; Skill execution never downloads or installs them.

```sh
llama-server --model /approved/qwen.gguf --alias agentforge-local-qwen --host 127.0.0.1 --port 31871 --offline --no-ui --no-agent --no-slots --cors-origins http://127.0.0.1:31871 --no-cors-credentials --threads 8 --ctx-size 8192 --parallel 1
```

The native server/model parser is trusted operator software. Keep it on loopback,
restrict browser origins, disable tools, and stop it after use. It has no mechanism
to execute generated source. That source must pass builder checks and run only in
the independently selected sandbox.

Example `local-model.json`:

```json
{
  "model": "agentforge-local-qwen",
  "max_output_tokens": 2048,
  "max_requests": 2,
  "total_token_limit": 40000,
  "max_cost_usd": 0,
  "input_usd_per_million": 0,
  "output_usd_per_million": 0,
  "timeout_seconds": 180
}
```

```sh
agentforge budget create local-development --usd 0 --tokens 500000 --requests 10
agentforge build reviewed.plan.json --local-model http://127.0.0.1:31871/v1/chat/completions --approve-local-model --model-config local-model.json --budget-account local-development --model-receipts new-receipts.json --output skills/reviewed-name
python tools/qualify_domains.py --runtime-config wasi-policy.json --local-endpoint http://127.0.0.1:31871/v1/chat/completions --model-config local-model.json --approve-local-model --output new-real-model-evidence
```

Only literal `127.0.0.1`/`::1`, HTTP, an explicit port and the exact chat path are
accepted. Hostnames, remote addresses, URL credentials, redirects and inherited
proxies are rejected. Local calls require zero monetary rates and a persistent
token/request account. Paid OpenAI calls retain separate approval/credential gates.

Local generation uses typed source/tests/example fields so the trusted builder
serializes JSON files correctly. Source remains actual model output; it is never
replaced with an authored implementation. Python/WASM prompts use the selected
target's ABI. Generated tests do not determine independent acceptance. Evaluator
cases stay outside both model requests and Skill artifacts.

`build` and `evolve` accept up to three `--example-input FILE` arguments for public
operator-reviewed JSON inputs. These files contain inputs only, never expected
outputs. The generator must calculate results and implement the full contract.
Inputs are checked against the sealed schema, sensitive-value filter and a shared
4 KiB size cap before inference. This is optional input assistance, not an
independent answer key; never supply evaluator-owned inputs through this option.

Repair feedback identifies generated tests as fallible observations. A model can
repair generated expectations or invalid example inputs while preserving correct
source. Semantic preconditions in the goal apply even if the JSON schema cannot
express them. The model's diagnosis is audit data, never an acceptance decision.
Private-only failures trigger a repair request without disclosing private cases.

For reproducible eight-domain acceptance, use a model config allowing three
requests per domain and `--repair-iterations 2 --seconds 2700`. Each domain has
16 independent positive cases and two invalid-root checks. A separately recorded
subset trial can use `--domain csv-row-sums`; failed original trials are retained.
After stopping the model server, run fresh deterministic evaluator seeds without
additional inference:

```sh
python tools/recheck_domains.py --summary new-real-model-evidence/summary.json --runtime-config wasi-policy.json --output fresh-holdouts
```

`tools/qualify_model_repair.py --help` describes a bounded actual-model repair and
regression experiment. It mutates one AST operator in an existing genuine model
artifact, executes it only in WASI, then requires independent acceptance of the
model repair and rejection of a subsequent deliberately regressing candidate.

`tools/qualify_planning.py --help` exercises actual free inference for both planning
and source generation, followed by independently computed ASCII digit-count cases.
Planning requests ask for an editable specification rather than program source.
Local plans use typed schema objects. Unspecified scaffold root types are omitted
from model context; `plan --contract FILE` seals the operator's explicit schemas.
`--review-plan` opts into one additional free-local self-review request, with both
attempts retained. Planning plus self-review plus build needs at least three requests
and sufficient token reservations (the recorded trial allows 100000 tokens).
Review is not an independent test and can still miss a semantic contradiction.
Larger qualification sets are partitioned into at most 32 independent cases per
engine call. Generated/integration checks repeat across batches; reports distinguish
those executed counts from the number of unique independent inputs.

Small local models can fail generation or behavioral acceptance; those outputs are
rejected and recorded. A few successful domains do not establish arbitrary-goal
synthesis quality or paid-provider quality/cost acceptance.
