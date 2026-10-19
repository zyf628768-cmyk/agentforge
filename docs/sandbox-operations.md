# Python sandbox operation and crash recovery

Use a dedicated non-production Linux machine for qualification. Rootless Docker
must have cgroup v2 with the systemd driver and delegated CPU, memory and PID
controllers, seccomp, and the official gVisor/runsc runtime. A regular Docker
container, venv or subprocess does not satisfy this policy.

Provisioning is an operator action. Skill execution never installs packages,
downloads an image or changes daemon configuration. Select an already-installed
immutable image digest and a socket owned by the current nonroot Linux user:

```json
{
  "image": "python@sha256:REPLACE_WITH_REVIEWED_LOCAL_DIGEST",
  "socket": "unix:///run/user/1000/docker.sock",
  "lease_dir": "/absolute/private/operator-directory/agentforge-leases"
}
```

The placeholder is intentionally rejected until replaced with an actual approved
digest. The lease directory must be private (0700) and outside Skill artifacts.
Do not place it in a guest mount or ephemeral CLI working directory.

Run the supervisor as a separate service:

```console
agentforge sandbox supervise --container-config /absolute/container-policy.json
agentforge sandbox status --container-config /absolute/container-policy.json
agentforge doctor --container-config /absolute/container-policy.json
```

Example **user** systemd unit; replace all absolute paths for the installation:

```ini
[Unit]
Description=AgentForge sandbox lease supervisor
After=docker.service
Requires=docker.service
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/absolute/venv/bin/agentforge sandbox supervise --container-config /absolute/container-policy.json
Restart=always
RestartSec=1
TimeoutStopSec=10
NoNewPrivileges=yes
UMask=0077

[Install]
WantedBy=default.target
```

Enable this unit in the operator's user manager after installing it. It supervises
only the selected rootless daemon and policy. A service manager must restart it
after unexpected failure. Boot recovery also requires the rootless daemon/user
manager to start; configure lingering only on the dedicated sandbox host.

## Lease semantics

An fsynced SQLite lease and random container name are committed **before** create.
Only matching policy/lease labels can be cleaned up. The supervisor records a
heartbeat after each successful inventory/recovery sweep. New executions refuse
missing, dead, reboot-mismatched or stale supervision. Both monotonic and wall
deadlines are checked; a reboot expires old leases. Per-suite lifetime is at most
30 seconds. Staging contains scripts only, readable to the guest's nonroot UID.

Normal cleanup removes the container before its staged code. Failures retain
cleanup-pending state; the independent service retries after daemon recovery.
Closed-lease tombstones plus daemon inventory catch create requests which finish
after a control-client timeout. Another policy's or an unknown container is never
deleted. `agentforge sandbox reap --container-config FILE` runs one recovery sweep.

The lease deadline is not a hardware hard TTL during a daemon, OS or supervisor
outage. Recovery depends on the service manager and daemon becoming available.
Do not claim uninterrupted cleanup guarantees during host failure. Keep the state
database durable; a local operator able to rewrite it is outside the threat model.

## Actual qualification

```console
python tools/qualify_container.py --container-config container-policy.json --output actual-evidence
```

This refuses unsuitable hosts before starting any adversarial source. It runs a
CSV Skill with independently held cases and probes guest filesystem/network,
environment, UID, memory, fork, output and time limits, then kills the calling CLI
to verify independent reaping. In an **explicit disposable CI VM only**, add
`--restart-disposable-daemon` to test daemon/supervisor recovery as well.

The `real-rootless-gvisor` GitHub workflow provisions only its disposable VM,
checks the official archive checksum and records actual commands and results.
Its report must say `actual_runtime: true`, `mocked_daemon: false` and `passed`;
missing runtime, skipped probes and protocol mocks are never a successful result.

References: [gVisor rootless](https://gvisor.dev/docs/user_guide/rootless/),
[Docker resource delegation](https://docs.docker.com/engine/security/rootless/tips/),
[official gVisor installation](https://gvisor.dev/docs/user_guide/install/).
