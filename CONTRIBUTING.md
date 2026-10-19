# Contributing

Use Python 3.11+ and Git. Install with `python -m pip install -e '.[dev]'`.
Run `python -m pytest -q`, `ruff check src tests tools`, and the three demos
before proposing a change. Keep execution evidence reproducible and report blocked
checks as blocked. CI tests Python 3.11–3.13 on Linux and Windows.

Implement generator backends through `Generator.generate`. Generation returns files,
never trusted evaluation claims. Add evaluator-owned independent cases for new
semantics. Do not add host execution of unreviewed generated Python, implicit network
access, secret discovery, automatic publication or paid calls. See SECURITY.md.

Do not overwrite accepted versions or mutate old snapshots. Add a new version and
compare it against the old one. Include meaningful behavior/regression tests.
