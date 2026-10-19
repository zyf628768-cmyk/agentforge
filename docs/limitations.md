# Known limits — 0.2.0a1

- Generic generation accepts provider-produced source for compute-only JSON WASM
  and standard-library Python. It does not guarantee arbitrary requested capability
  correctness. Human contracts and independently authored acceptance remain required.
- The real Responses wire adapter is implemented. No paid/live model quality,
  latency, availability or billing was tested; fixtures are authored, labelled data.
- Generic WASM is actually executed with OS containment on Windows. Linux rlimit
  behavior and cross-platform CI remain to be physically verified.
- Python requires the strict local rootless gVisor environment and approved image.
  This host lacks it. Only artifact generation, refusal and mocked adapter policy
  tests ran; no arbitrary Python sandbox execution is claimed.
- Container crash/daemon-loss cleanup needs a durable reaper before production.
- No network tools, writable host files, automatic packages, services or capability
  grants are supplied to generated Skills. Schemas intentionally use a bounded
  reference-free/regex-free subset. Memory/input/module/case limits apply.
- Model reservations are per invocation, based on reviewed configured rates and
  conservative token allowances. They are not an account-wide billing guarantee.
- Public example holdouts prevent accidental test deletion, not deliberate gaming.
- Independent security review, live-model acceptance, deployment authentication,
  persistent accounting and operational readiness are outstanding. See readiness.md
  via [production checklist](production-readiness.md).
