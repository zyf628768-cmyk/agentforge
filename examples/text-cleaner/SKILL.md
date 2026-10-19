---
name: text-cleaner
description: Clean text by collapsing ASCII whitespace; use for local text normalization while preserving Unicode and case.
license: MIT
metadata:
  runtime: AgentForge 0.1 with Wasmtime; no network required
---

# Text cleaning

Pass a JSON object with a text string on standard input.
Run through the trusted AgentForge WASM engine:

```sh
agentforge test .
agentforge run . --input examples/input.json
```

The executable is scripts/clean.wasm; do not execute generated Python on the host.
See schemas/input.json and examples/ for the contract. ASCII whitespace is collapsed; other Unicode characters and letter case are preserved.
