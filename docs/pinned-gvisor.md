# Pinned rootless gVisor qualification

The qualification build uses the complete upstream rootless/systemd fix at
`google/gvisor@8ecc635e5e32b8eb1cb2acdc308d480f00bf7264`, including the mandatory
controller check. Its [upstream PR](https://github.com/google/gvisor/pull/13853)
is still open. A successful AgentForge qualification of this exact build does not
mean that upstream merged it or that unrelated runtime versions are qualified.

`tools/ci/build_gvisor.sh` fetches the exact Git object, verifies Bazel 8.3.1 with
SHA-256 `17247e8a84245f59d3bc633d0cfe0a840992a7760a11af1a30012d03da31604c`, builds
runsc and its matching checkpoint/metric sidecars together, runs the upstream
cgroup unit tests, and writes hashes and source provenance. No floating `latest`
binary or mixed-version sidecars are used.

The CI workflow can reuse the unit-tested build from repository run `39300341140`.
Its manifest SHA-256 is pinned to
`1695472a3820e3ab45a3727e634d15d803847bb9fe812d8a66a21295ecb38587`;
the provisioner independently verifies every binary hash. The CI token has only
repository contents/artifact read access. A manual `rebuild_runtime` request, or
expiry of that artifact, rebuilds the same fixed source and reruns upstream unit
tests. Reusing a built runtime does not imply that a prior guest qualification
passed. The Python base image is fixed to the tested immutable digest as well.

On a dedicated, disposable Ubuntu 24.04 x64 development VM:

```sh
bash tools/ci/build_gvisor.sh /absolute/new-gvisor-runtime
bash tools/ci/rootless-gvisor.sh /absolute/new-gvisor-runtime REVIEWED_MANIFEST_SHA256
python tools/qualify_container.py --container-config sandbox-policy.json --output new-sandbox-evidence --restart-disposable-daemon
```

These explicit provisioning commands install free build/runtime packages and
configure only the disposable development VM. They are never called by a Skill.
Review runtime provenance and all file hashes before installation outside CI;
pass the separately approved manifest hash to the provisioning command.

Execution retains rootless Docker, cgroup v2, seccomp, runsc, nonroot guest UID,
read-only mounts/root, network none, PID/memory/CPU limits and a live independent
lease supervisor. No ignore-cgroups, rootful execution or native-host guest fallback
is introduced.

Qualification checks a real, positively controlled host listener rather than an
unused port. Memory qualification requires a successful allocation below the cap
and a specific OOM/MemoryError above it. A two-worker CPU workload must produce
actual kernel throttling while the host observes `cpu.max`, `memory.max` and
`pids.max`. Missing observations fail qualification. Output limits, wall time,
fork limits, filesystem/environment restrictions and caller/daemon/supervisor
crash recovery are exercised separately. Real job results and failed attempts are
retained in release evidence; merely building the runtime does not pass these checks.
