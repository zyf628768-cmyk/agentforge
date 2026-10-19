# Third-party runtime and model assets

AgentForge source is MIT except files carrying explicit third-party notices.
Dependency wheels retain their own package licenses and metadata; inclusion in an
offline wheelhouse does not relicense them. Retain those notices when redistributing.

The optional native gVisor release asset contains the upstream Apache-2.0 license
as `LICENSE.gvisor`. Its manifest identifies exact source and matching sidecars.
The versioned systrap patch adds files with explicit Apache-2.0 headers and is
applied only to that separately built upstream runtime. It is not bundled into the
AgentForge Python wheel. The native runtime may only be installed explicitly by
an operator; generated Skills cannot install or switch it.

The optional official CPython/WASI runtime retains `LICENSE.cpython` and its
hash-bound provenance. The wheel itself does not silently download or provision it.

Official llama.cpp binaries and Qwen GGUF weights are separately provisioned
operator assets, not included in this project's release ZIP or wheelhouses.
Recorded provenance identifies upstream revisions, source URLs and hashes. Model
licenses apply to the model files; AgentForge's MIT license does not cover them.

Qualification artifacts contain generated programs and deliberately failing or
hostile examples as evidence. Inspect them as untrusted data and execute only
through an explicitly supported sandbox. Packaging does not activate or publish
them to an Agent Skills registry.
