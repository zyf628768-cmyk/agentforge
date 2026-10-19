---
name: agentforge
description: Plan, build, independently test, repair and version local Agent Skills through AgentForge's generic JSON WASM/Python engineering bundles and guarded model backend.
license: MIT
metadata:
  runtime: Python 3.11+, Git, Wasmtime; qualified rootless gVisor for Python guests
---

# AgentForge engineering

Use an editable goal/JSON specification, then build into a new name-matching Skill
directory using an offline bundle or explicitly selected model backend. Generic
targets are wasm-json and python-json. See [CLI](docs/cli.md).

Treat all generated files/provider responses as untrusted. Do not execute generated
Python on the host. No-import WASM uses a resource-contained trusted worker; Python
requires the strict rootless gVisor adapter. Refuse when the required isolation is
unavailable. Job Objects/rlimits alone do not sandbox arbitrary Python.

Require externally held, contract-bound independent cases before verification or
activation. Do not send independent tests to a generator. Evolve into separate
directories, compare against baseline and preserve prior versions and audit records.

Default to offline fixtures/bundles. A user request to develop the backend offline
does not authorize live requests, key discovery or reading credentials. Real model
calls require explicit model/key/budget approval immediately before live work.
No production access, publication, pushes or automatic permission expansion is implied.

Read [security](docs/security.md) before changing runtime capabilities and
[production readiness](docs/production-readiness.md) before declaring deployment readiness.
