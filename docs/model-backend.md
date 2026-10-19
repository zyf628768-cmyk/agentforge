# Model backend and live-call boundary

`ResponsesBackend` accepts an injected `Transport`. `RecordedTransport` is offline;
`OpenAITransport` implements HTTPS POST to the fixed OpenAI Responses endpoint.
The CLI has no automatic endpoint fallback, proxy inheritance or credential search.
Redirects are rejected. Responses are bounded and must contain completed strict
structured output with usable usage metadata. Refusal, incomplete output, malformed
JSON or unusable accounting fails the operation and retains its reservation.

The request uses `store=false`, `max_output_tokens`, `text.format.type=json_schema`
with `strict=true`, and no tools. See [official structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
The engineering response is `{files:[{path,content}]}`. The trusted builder seals
metadata and compiles WAT in a quota-controlled worker. Python is only eligible
for the strict container adapter. A response cannot select a weaker executor.

Model planning returns an editable `spec_json` string, validated locally. Goal,
name, version and target identity cannot silently change. Arbitrary JSON schemas
are intentionally limited to a bounded reference-free, regex-free subset to avoid
network resolution and expensive schema programs. Dependency installation is absent;
Python targets use approved-image standard-library capabilities only.

Config fields (all explicit; no default live model):

```json
{
  "model": "REVIEW_AND_SELECT_A_MODEL",
  "max_output_tokens": 4096,
  "max_requests": 2,
  "total_token_limit": 40000,
  "max_cost_usd": 0,
  "input_usd_per_million": 0,
  "output_usd_per_million": 0,
  "timeout_seconds": 30
}
```

This is a review template; zero spend or zero prices **disable live requests**.
Only after human approval, supply reviewed positive values and select a credential
variable explicitly. `--approve-model-request` and `--credential-env` are both
required. The selected variable is read once only after gates pass; it is not
logged or forwarded to workers. A new `--model-receipts` file outside Skill artifacts
is mandatory. This development session used no actual key or provider request.

Before each request, the backend reserves a conservative byte-based input allowance
plus maximum output tokens using the configured rates. Request count, token total,
deadline and spend cap are checked before transport. Actual usage is recorded;
unknown outcomes retain worst-case reservations and are not blindly retried.
Unexpected usage beyond the reservation requires manual reconciliation. This is
not a provider-enforced account cap; tokenization/prices/server accounting and
cross-process billing must be qualified before production. No automatic price fetch
or paid model selection occurs.

`ModelGenerator` repair feedback includes failed generated/example cases only.
Evaluator-owned independent cases and their expected outputs are never sent in
model requests. Public checked-in example holdouts are not secret benchmarks; a
production evaluator must own its private acceptance corpus outside the project.
