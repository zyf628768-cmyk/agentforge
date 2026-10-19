# Free local model inference

The loopback llama.cpp backend performs actual inference, labelled
`local-llama.cpp` with `offline_fixture: false`. Authored protocol data remains
labelled as fixtures. No provider credentials are discovered or needed.

Provision trusted official binaries and a reviewed GGUF separately; record immutable
revisions, SHA-256, source URLs and licenses. The local acceptance uses official
Qwen/Qwen2.5-Coder-3B-Instruct-GGUF and Qwen/Qwen2.5-Coder-7B-Instruct-GGUF Q4_K_M,
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

Small local models can fail generation or behavioral acceptance; those outputs are
rejected and recorded. A few successful domains do not establish arbitrary-goal
synthesis quality or paid-provider quality/cost acceptance.
