# Actual free local model results

Official Qwen2.5-Coder 3B and 7B Instruct Q4_K_M weights were hash-verified and
executed using official llama.cpp b11669 on this Windows CPU host. Model weights
and native inference software are separate operator assets, not covered by this
project's MIT license. No paid API, provider key discovery or production access
was used. Each server binds literal loopback, disables tools/UI and is stopped
after its bounded phase.

The evaluator has 16 independent cases per domain. Their inputs, expected outputs
and authored reference implementations are not supplied to the model. Genuine
model source runs inside the separately approved CPython/WASI backend. Typed JSON
serialization by the builder does not substitute authored source for model output.

| Trial | Invoice totals | Interval union | Unicode word histogram |
|---|---|---|---|
| 3B retained artifacts, before controlled repair | 16/16 independent; rejected for incorrect generated expectations | 13/16 independent; rejected | 0/16 independent; rejected |
| 7B initial generation, one request per domain | 16/16 independent, 17/19 total; rejected for incorrect generated expectations | 16/16 independent, 19/19 total; passed | 0/16 independent; rejected for treating a string root as a wrapper object |

These are measured artifact outcomes, not statistical model rankings. Trials used
evolving engineering prompts; they do not constitute a controlled 3B/7B comparison.
The initial raw failures remain part of the evidence. Follow-up controlled repair
and root-contract prompt trials are reported separately with their own receipts,
budgets and actual outcomes in the release evidence. A failed initial result is
not overwritten when a later trial runs.

Actual testing also found two engine integration issues: model-copied integration
case names could collide with engine IDs, and local typed prompts needed explicit
root-value semantics. Case suites now have separate namespaces with original labels
preserved; the prompt explains direct string/array/object contracts. No holdout is
added to repair context. Incorrect generated tests remain failures rather than
being silently changed to match the program.

Model generation and model repair can fail within their finite budgets. Independent
gates refuse such candidates and preserve existing stable versions. This evidence
establishes an actual free inference/engineering/sandbox path and its observed
limits; it does not establish arbitrary-goal production quality, paid-provider
acceptance or an independent human security verdict.
