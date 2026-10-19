"""Provider-neutral engineering bundles. All model output is untrusted data."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path, PurePosixPath

from .contracts import check_cases
from .core import ForgeError, artifact_destination, read_json, redact, strict_json, write_json
from .sandbox import Sandbox
from .spec import validate

BUNDLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["files"],
    "properties": {
        "files": {
            "type": "array",
            "minItems": 5,
            "maxItems": 40,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "content"],
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
        }
    },
}


def safe_bundle(bundle: dict, kind: str) -> dict[str, str]:
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(BUNDLE_SCHEMA).is_valid(bundle):
        raise ForgeError("Model response is not an engineering file bundle")
    result = {}
    seen = set()
    total = 0
    for item in bundle["files"]:
        name, content = item["path"], item["content"]
        path = PurePosixPath(name)
        if name.casefold() in seen or any(
            part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(10)),
                *(f"LPT{i}" for i in range(10)),
            }
            for part in path.parts
        ):
            raise ForgeError("Case-colliding or Windows device artifact path")
        seen.add(name.casefold())
        if (
            not re.fullmatch(r"[a-zA-Z0-9_./-]{1,150}", name)
            or path.is_absolute()
            or str(path) != name
            or any(
                part in {".", ".."} or part.startswith(".") or ":" in part for part in path.parts
            )
        ):
            raise ForgeError("Unsafe artifact path")
        reserved = {"manifest.json", "spec.json", "SKILL.md", "config.json"}
        if name in reserved or name.startswith("schemas/") or name.endswith(".wasm"):
            raise ForgeError("Provider may not override sealed metadata or binary artifacts")
        if not (
            name == "README.md"
            or name.startswith(("scripts/", "tests/", "examples/", "references/"))
        ):
            raise ForgeError("Unsupported artifact location")
        if path.suffix not in {".py", ".wat", ".json", ".md", ".txt", ".csv"} or name in result:
            raise ForgeError("Duplicate/unsupported artifact file")
        if redact(content) != content:
            raise ForgeError("Potential secret in model output; artifact rejected")
        total += len(content.encode())
        if len(content.encode()) > 100_000 or total > 500_000:
            raise ForgeError("Engineering bundle exceeds size budget")
        result[name] = content
    entry = "scripts/main.wat" if kind == "wasm-json" else "scripts/main.py"
    required = {
        entry,
        "README.md",
        "tests/cases.json",
        "examples/input.json",
        "examples/output.json",
    }
    if not required <= result.keys():
        raise ForgeError("Bundle lacks executable code, tests, README or examples")
    for name in ("tests/cases.json", "examples/input.json", "examples/output.json"):
        try:
            value = strict_json(result[name])
        except (ValueError, RecursionError) as exc:
            raise ForgeError("Invalid bundled JSON") from exc
        if name == "tests/cases.json" and (
            not isinstance(value, list) or not 1 <= len(value) <= 32
        ):
            raise ForgeError("Bundle requires 1..32 behavioral cases")
    return result


class BundleGenerator:
    def __init__(self, bundle: dict, *, source: str = "reviewable-artifact-bundle"):
        self.bundle = bundle
        self.source = source

    @classmethod
    def from_file(cls, path: Path):
        return cls(read_json(path))

    def generate(self, spec: dict, destination: Path, variant: str = "correct") -> Path:
        validate(spec)
        if spec["kind"] not in {"wasm-json", "python-json"} or variant != "correct":
            raise ForgeError("Bundle generation requires a generic JSON runtime")
        artifact_destination(destination, spec["name"])
        contents = safe_bundle(self.bundle, spec["kind"])
        check_cases(strict_json(contents["tests/cases.json"]), spec)
        from jsonschema import Draft202012Validator

        if not Draft202012Validator(spec["inputs"]).is_valid(
            strict_json(contents["examples/input.json"])
        ) or not Draft202012Validator(spec["outputs"]).is_valid(
            strict_json(contents["examples/output.json"])
        ):
            raise ForgeError("Examples must conform to the sealed JSON schemas")
        entry_source = "scripts/main.wat" if spec["kind"] == "wasm-json" else "scripts/main.py"
        if not contents[entry_source].strip():
            raise ForgeError("Executable implementation cannot be empty")
        binary = (
            Sandbox().compile(contents["scripts/main.wat"]) if spec["kind"] == "wasm-json" else None
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Stage all files before publication; an invalid bundle never leaves a partial Skill.
        with tempfile.TemporaryDirectory(prefix="agentforge-stage-", dir=destination.parent) as tmp:
            staged = Path(tmp) / spec["name"]
            staged.mkdir()
            for relative, content in contents.items():
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            if binary is not None:
                (staged / "scripts/main.wasm").write_bytes(binary)
            entrypoint = "scripts/main.wasm" if binary is not None else "scripts/main.py"
            compatibility = (
                "agentforge-json-wasm-1" if binary is not None else "agentforge-json-python-1"
            )
            write_json(staged / "spec.json", spec)
            write_json(staged / "schemas/input.json", spec["inputs"])
            write_json(staged / "schemas/output.json", spec["outputs"])
            write_json(staged / "config.json", {"runtime": spec["kind"], "capabilities": []})
            (staged / "SKILL.md").write_text(
                f"---\nname: {spec['name']}\ndescription: Execute the {spec['name']} JSON capability through AgentForge after independent evaluation.\nlicense: MIT\n---\n\n"
                "# Isolated JSON Skill\n\n"
                "Use `agentforge run . --input examples/input.json`. Treat every generated file as untrusted.\n"
                "Never run generated Python on the host. No network, host files or credentials are granted.\n"
                "Use `agentforge test . --evaluation /reviewed/evaluation.json` for independent acceptance.\n"
                "Schemas describe the JSON contract. Inspect spec.json and README.md for the intended behavior.\n",
                encoding="utf-8",
            )
            write_json(
                staged / "manifest.json",
                {
                    "name": spec["name"],
                    "version": spec["version"],
                    "kind": spec["kind"],
                    "source": self.source,
                    "entrypoint": entrypoint,
                    "sha256": hashlib.sha256((staged / entrypoint).read_bytes()).hexdigest(),
                    "dependencies": [],
                    "compatibility": compatibility,
                },
            )
            from .validation import inspect_skill

            checks = inspect_skill(staged)
            if not checks["passed"]:
                raise ForgeError("Generated artifact rejected: " + "; ".join(checks["errors"]))
            staged.rename(destination)
        return destination
