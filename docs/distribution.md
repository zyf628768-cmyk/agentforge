# Native offline distributions

The `offline-distribution` workflow builds independent Windows x64 and Ubuntu
Linux x64 wheelhouses for Python 3.11, 3.12, 3.13, 3.14 and 3.15. Each job creates
a new venv, installs with `--no-index`, checks dependencies, starts every CLI,
executes the full test suite and runs the three original demonstrations.

Each artifact contains `wheelhouse/` and `offline-evidence/`, including real commands,
exit codes, JUnit and platform metadata. Do not use Windows native dependency
wheels on Linux, or a CPython-specific wheelhouse on another Python minor version.
Build setup can download free dependencies and build missing native wheels; the
fresh installation test cannot fall back to an index.

After extracting the artifact appropriate for your platform:

```sh
python -m venv .venv
# Activate the environment for your platform.
python -m pip install --no-index --find-links wheelhouse agentforge
agentforge doctor
```

To reproduce the qualification from a source checkout:

```sh
python -m pip wheel --wheel-dir wheelhouse '.[dev]'
python tools/verify_offline_install.py --wheelhouse wheelhouse --venv work/new-env --output new-offline-evidence
```

CPython/WASI is provisioned and hash-approved separately. It is portable between
qualified Windows/Linux hosts and is not a native third-party Python wheelhouse.
The free local LLM's large weights and binaries are also explicit operator assets;
release packages retain their provenance rather than silently fetching them.
macOS, ARM and future Python versions are not qualified by these x64 jobs.
