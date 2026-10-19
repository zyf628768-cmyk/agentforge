# Changelog

## 0.2.0a2 — sandbox recovery and qualification

- Persist leases before container creation; independently supervise expiry, crashes,
  late daemon responses and cleanup retries. Refuse execution without a live supervisor.
- Attest container identity, entrypoint, arguments, tmpfs, ulimits, logging, restart
  policy and auxiliary privileges before starting guest code.
- Correct nonroot staging permissions; restrict the selected socket's ownership.
- Add actual rootless-gVisor qualification with hostile guest and crash probes.
- Correct obsolete publication and cross-platform CI statements in both READMEs.

## 0.2.0a1 — offline production-readiness milestone

- General JSON contracts and provider-neutral executable engineering bundles.
- OpenAI Responses wire backend, offline transport fixtures, guarded live requests, token/cost reservations and receipts.
- General WASM JSON ABI; numeric repair and independent regression evaluation.
- Windows Job Object quotas, contained WAT compilation and Linux rlimit worker.
- Fail-closed rootless gVisor Python adapter with local-only policy, bounded streams and pre-start settings attestation.
- Atomic version activation, artifact write protection, strict JSON and redacted database evidence.
- Live-model quality, real Linux/container integration, crash reaping and independent audit remain production blockers.

## 0.1.0 — 2026-10-19

- Editable capability specifications with JSON Schema and semantic validation.
- Offline text-cleaner compiler emitting working WASM, WAT, Python wrappers,
  JSON tests, examples, schemas, README and standard SKILL.md.
- No-import Wasmtime execution with real command, exit and result evidence.
- Independent evaluation, deterministic defect repair, regression rejection,
  iteration/time/cost bounds and immutable version directories.
- SQLite registry, local Git snapshots, search, export and active-pointer rollback.
- Full CLI, reproducible demos, acceptance suite and CI matrix.
