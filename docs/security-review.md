# Security review evidence and remaining independent gate

Automated review uses independent scanner implementations, pip-audit and Bandit.
Run `python tools/security_audit.py --output NEW_DIRECTORY` in a trusted development
environment with those free tools installed. It saves real commands, exit codes,
runtime dependency versions and raw findings. Dependency checks send package
names/versions to the advisory service, not Skill source or credentials.

This is not an independent human security audit. Before production, an independent
reviewer must assess Wasmtime/CPython/native runtime assumptions, quota enforcement,
model protocol/receipt boundaries, crash recovery and operator state integrity.

The first scan found no known advisories for the installed runtime dependency set.
That statement is bounded to the recorded versions/advisory response and date;
it does not prove absence of vulnerabilities in native runtimes or model files.

Bandit findings are retained rather than globally suppressed:

| Finding | Reviewed boundary / disposition |
|---|---|
| B404 subprocess imports | Trusted engine/control/snapshot code uses subprocesses; an import is not itself an escape. Generated source is never passed to native Python. |
| B603 subprocess arguments | Commands are lists without a shell. Guests enter only Wasmtime or the inspected gVisor runtime. Git commands operate on trusted registry state with hooks/global config disabled. |
| B108 `/tmp` literal | This is an attested, bounded in-guest tmpfs, not an insecure shared host temporary filename. Host staging uses private operator leases or TemporaryDirectory. |
| B607 Git lookup | Changed Git execution to use the resolved absolute executable. Operator executable search paths remain trusted. |

Re-run after source changes and inspect new findings; raw scanner exit 1 is not
reported as a clean scan. Existing hostile guest probes complement scanner review.
They do not establish resistance to every kernel/JIT/native dependency defect.

The gVisor rootless/systemd fix remains an open, conflicting upstream PR at the
time of investigation: `google/gvisor#13853`, head
`8ecc635e5e32b8eb1cb2acdc308d480f00bf7264`. Its substantial UID-namespace, D-Bus and
cgroup changes cannot be treated as a reviewed stable runtime. AgentForge retains
the failed-start evidence and strict refusal; it does not disable cgroups, use
rootful execution, or silently ship a patched native sandbox as production-ready.
