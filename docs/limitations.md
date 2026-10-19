# Known limits — 0.2.0a4

- General generation accepts actual provider-produced source for compute-only JSON
  WASM and standard-library Python. New goals still require a reviewed contract and
  separately held acceptance cases. A finite domain suite cannot guarantee every
  possible goal or future model output; failed candidates are retained and rejected.
- Actual free local inference, including model repair, has separate receipts and
  source artifacts. The paid Responses adapter has offline HTTP/protocol tests;
  paid-provider quality, availability, latency and actual billing were excluded by
  the user. No real provider credential was discovered or read.
- Native wheelhouses qualify Windows/Linux x64 with Python 3.11–3.15. macOS, ARM,
  third-party native Python extensions and arbitrary network services are outside
  the tested execution profile. CPython/WASI supports pure compute and bundled
  read-only helpers; it is explicitly selected rather than an automatic fallback.
- The rootless gVisor profile uses a fixed source build of an open upstream PR.
  [Its provenance and qualification](pinned-gvisor.md) apply to that exact build
  and disposable Ubuntu profile. They do not establish upstream merge status or
  qualify every runsc/kernel/container-image combination. Operators approve the
  runtime manifest and immutable image before use; failed preflight refuses code
  execution without dropping controls or running guest Python on the host.
- Container cleanup requires the independent supervisor to be operated under a
  restarting service manager with durable private lease storage. A daemon/host
  outage delays cleanup until recovery; a software lease cannot enforce an
  independent hardware wall-time limit while the machine or daemon is unavailable.
- No network tools, writable host files, automatic packages, services or capability
  grants are supplied to generated Skills. Schemas use a bounded subset without
  references or regex. Memory/input/module/case limits apply.
- Atomic request/token/money reservations span processes and restarts sharing one
  explicit home/account. They are not a provider-enforced account-wide spending
  cap. Unknown results retain reservations until explicit operator reconciliation.
- Reproducible public evaluator cases detect accidental regressions and deletion;
  use private cases for adversarial submissions. Independent cases are withheld
  from inference, repair context and mounted candidate source.
- The user confirmed human review passed; [the attestation](human-review-attestation.json)
  records that statement without inventing reviewer identity, revision or report.
  Automated findings and later changes remain separately attributable.
- This release is a local engineering CLI. A hosted multi-tenant service would
  need its own deployment, authentication, backup and operational design.
