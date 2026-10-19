# Actual free local model results

Official Qwen2.5-Coder 14B Instruct Q4_K_M was executed using official
llama.cpp b11669 on Windows CPU. Weight SHA-256:
`c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940`.
The release includes exact upstream revisions, commands, token/request budgets,
receipts, source hashes and original failed trials. Weights are separately licensed
operator assets; they are not bundled or relicensed as MIT.

| Domain | Observed accepted path |
|---|---|
| Invoice totals | Actual model generation |
| Closed interval union | Actual generation, failure detected, actual model repair |
| Unicode casefold histogram | Actual model generation |
| Stable unique values | Actual model generation |
| Matrix transpose | Actual model generation |
| Reduced fractions | Actual model generation |
| Signed numeric CSV row sums | Input-assisted actual generation, after rejected unassisted trials |
| Balanced brackets | Actual model generation |

The original eight-domain batch failed: CSV code passed independent cases but its
own examples violated the numeric-cell goal. Two model repairs were rejected.
Follow-up failures remain in the evidence. The successful CSV trial supplied only
two public input values, without expected answers; the model generated both code
and expectations. No source or expected output was manually replaced.
This is seven unassisted domains plus one input-assisted domain, not an eight-domain
unassisted success rate or a controlled statistical model ranking.

All eight accepted artifacts then passed a fresh-seed evaluation: **410 distinct
independent cases** and **458 executed checks**, including repeated generated and
integration checks. Cases are deduplicated within that evaluation; fixed edges can
overlap earlier suites. Inputs and answers remain outside model context. Evaluation
is split into batches under the unchanged 32-case engine limit.

A separate actual-model repair demonstration deliberately changes one multiplication
to addition in accepted invoice source. A real bounded model repair passes; a later
regressive candidate is rejected and the active SQLite/Git artifact hash remains
`a93261cfb2217f1d36fa32c4940232af0e3787edf5b5db6daf3f2571a659d957`.

Earlier official 3B/7B trials also remain available. They exposed incorrect generated
expectations and root-wrapper mistakes. Later success does not overwrite those
failures. Planning trials likewise retain failures and distinguish supplied
contracts, model self-review and independent behavioral acceptance.

Every inference server binds literal loopback, disables tools/UI and runs with a
minimal environment, finite Job Object resources and an explicit deadline. It is
stopped after the phase. Model source executes only inside CPython/WASI. No paid
requests, real credential discovery or production access were used.

These results qualify the recorded compute-only tasks and artifacts. They do not
establish arbitrary-goal reliability, paid-provider quality/billing or protection
against every native-engine vulnerability. See the release RESULTS files for
commands, precise counts, failed trials, CI runs and runtime provenance.
