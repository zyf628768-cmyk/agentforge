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

The runtime also applies the versioned patch
`tools/patches/gvisor-systrap-errno.patch` (SHA-256
`3afe5e6446da001e1af53d73893a9a50bc203ebc6613947828c30561d0271aee`).
An actual fork-limit probe discovered that systrap lost the kernel EAGAIN/ENOMEM
errno and panicked instead of returning it. The patch preserves only those exact
resource errors, retains unknown-error diagnostics and initializes references only
after successful creation. The build runs both upstream cgroup tests and new
systrap errno tests. It does not raise PID limits or disable cgroups.

The patch covers both stub-process and sysmsg-thread creation. The earlier
stub-only build is retained as failed evidence: another resource path still lost
errno during repeated fork pressure. It is not an approved substitute for the
current patch. Release provenance identifies the rebuilt runtime, both Go unit
suites, every binary hash and the exact qualifying CI run.

CI may reuse only the explicitly pinned rebuilt artifact and manifest hash. The
provisioner independently rechecks source, patch, both unit-test results and every
binary. Expired artifacts or an explicit rebuild compile the same source again.
Repository tokens have only contents/artifact read access.

The rebuilt binary passed both Go unit suites and all 13 actual checks in
[run 39310217680](https://github.com/zyf628768-cmyk/agentforge/actions/runs/39310217680).
Its manifest SHA-256 is
`92aaeb0dcc4f30df27f65c5fb04db690f9b3891ff4b58bc35adc538f8c5b8975`.
The subsequent strict qualifier repeats fork pressure three times and strengthens
output/watchdog evidence checks; its separate actual result is in release evidence.

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
three consecutive fork-limit trials with normal EAGAIN returns, filesystem/environment restrictions and caller/daemon/supervisor
crash recovery are exercised separately. Real job results and failed attempts are
retained in release evidence; merely building the runtime does not pass these checks.

Output qualification requires the exact bounded-stream error. Wall-time
qualification requires the watchdog timeout and live kernel observations.
Preflight failures, cleanup errors, generic exits and native panics never count as
successful output, timeout or graceful fork-denial checks.
