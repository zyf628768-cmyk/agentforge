# Security review evidence

On 2026-10-20, the user confirmed that human security review passed. The direct
statement and its provenance are saved in
[human-review-attestation.json](human-review-attestation.json). Reviewer identity,
covered revision and a written report were not supplied; this document does not
invent them or claim that the statement covers subsequent changes.

Automated review uses independent scanner implementations, pip-audit and Bandit.
Run `python tools/security_audit.py --output NEW_DIRECTORY` in a trusted development
environment with those free tools installed. It saves real commands, exit codes,
runtime dependency versions and raw findings. Dependency checks send package
names/versions to the advisory service, not Skill source or credentials.

These automated scans are separate from that user-confirmed human review.
[Review boundaries](review-handoff.md) remain available for reviewing changes to
Wasmtime/CPython/native runtime assumptions, quota enforcement, model protocol and
receipt boundaries, crash recovery and operator state integrity.

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

The gVisor rootless/systemd fix is still an open upstream PR, not a merged stable
release: `google/gvisor#13853`, head `8ecc635e5e32b8eb1cb2acdc308d480f00bf7264`.
The exact source plus a versioned errno-preservation patch is compiled and unit
tested, then exercised under the strict native profile. Earlier startup and
qualification failures remain in the evidence. See [runtime provenance](pinned-gvisor.md)
and release results; qualification never disables cgroups or uses rootful fallback.
