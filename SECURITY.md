# Security policy

Versions: 0.1.x legacy and 0.2.0a4 development milestone. No official remote private
reporting contact is configured for this local project; contact the eventual
maintainer privately before disclosing exploits or secrets publicly.

Generated code is untrusted. WASM has no imports/WASI and uses contained workers.
Python requires qualified rootless gVisor; no host fallback exists. Job/rlimit,
venv and subprocess are resource/process mechanisms, not arbitrary-code sandboxes.

Live models require explicit approval, selected credential variable, reviewed
budget/rates and audit output. No credential discovery or live calls were used
in this milestone's offline validation. Keep engine/runtime dependencies current.

Redaction/static scanning are best effort. Local database owners and native runtime
implementations are trusted. The container adapter lacks physically qualified crash
reaping and real-runtime security tests on this host; it is not production-qualified.
See [exact model and limits](docs/security.md) and [production gates](docs/production-readiness.md).
