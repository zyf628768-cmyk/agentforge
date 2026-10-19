"""Static inspections never import generated code or execute instructions."""

import ast
import hashlib
import importlib.util
import re
from pathlib import Path

import yaml

from .core import ForgeError, files, read_json, redact
from .spec import validate


def inspect_skill(root: Path) -> dict:
    errors = []
    try:
        paths = files(root)
        spec = validate(read_json(root / "spec.json"))
        generic = spec["kind"] != "text-cleaner"
        entry = (
            "scripts/main.py"
            if spec["kind"] == "python-json"
            else "scripts/main.wasm"
            if generic
            else "scripts/clean.wasm"
        )
        required = [
            "SKILL.md",
            "manifest.json",
            "spec.json",
            entry,
            "tests/cases.json",
            "README.md",
            "schemas/input.json",
            "schemas/output.json",
        ]
        if not generic:
            required.extend(["scripts/clean.wat", "scripts/run.py", "tests/test_skill.py"])
        for name in required:
            if not (root / name).is_file():
                errors.append("Missing " + name)
        if errors:
            return {"passed": False, "errors": errors}
        manifest = read_json(root / "manifest.json")
        spec = validate(read_json(root / "spec.json"))
        text = (root / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.+)", text, re.S)
        if not match:
            raise ForgeError("SKILL.md requires YAML frontmatter and body")
        front = yaml.safe_load(match[1])
        if not isinstance(front, dict):
            raise ForgeError("Frontmatter must be a mapping")
        name = front.get("name", "")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
            or len(name) > 64
        ):
            errors.append("Invalid Skill name")
        if name != root.name:
            errors.append("Skill name must match its directory name")
        description = front.get("description")
        if not isinstance(description, str) or not 1 <= len(description) <= 1024:
            errors.append("Description must have 1..1024 characters")
        if set(front) - {
            "name",
            "description",
            "license",
            "compatibility",
            "metadata",
            "allowed-tools",
        }:
            errors.append("Unsupported frontmatter field")
        if name != spec["name"] or manifest.get("name") != name:
            errors.append("Manifest/spec/frontmatter name mismatch")
        if manifest.get("version") != spec["version"]:
            errors.append("Manifest/spec version mismatch")
        if manifest.get("kind") != spec["kind"]:
            errors.append("Manifest/spec runtime mismatch")
        if manifest.get("entrypoint") != entry:
            errors.append("Only the bounded WASM ABI entrypoint is supported")
        abi = (
            "agentforge-json-python-1"
            if spec["kind"] == "python-json"
            else "agentforge-json-wasm-1"
            if generic
            else "agentforge-wasm-abi-1"
        )
        if manifest.get("compatibility") != abi:
            errors.append("Unsupported ABI")
        if manifest.get("dependencies") != []:
            errors.append("Guest dependencies unavailable: offline WASM permits none")
        if spec["kind"] != "python-json" and not importlib.util.find_spec("wasmtime"):
            errors.append("Missing runtime dependency: wasmtime")
        if (
            read_json(root / "schemas/input.json") != spec["inputs"]
            or read_json(root / "schemas/output.json") != spec["outputs"]
        ):
            errors.append("Contract schema mismatch")
        wasm = (root / entry).read_bytes()
        if len(wasm) > 100_000 or hashlib.sha256(wasm).hexdigest() != manifest.get("sha256"):
            errors.append("WASM size/hash mismatch")
        for path in paths:
            if path.suffix == ".py":
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in {"eval", "exec", "compile", "__import__"}
                    ):
                        errors.append("Unsafe Python dynamic execution")
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        modules = (
                            [a.name for a in node.names]
                            if isinstance(node, ast.Import)
                            else [node.module or ""]
                        )
                        if any(
                            m.split(".")[0] in {"os", "subprocess", "socket", "requests", "ctypes"}
                            for m in modules
                        ):
                            errors.append("Unsafe Python capability import")
            if path.suffix in {".py", ".json", ".md", ".wat"}:
                content = path.read_text(encoding="utf-8")
                if redact(content) != content:
                    errors.append("Possible secret in " + path.relative_to(root).as_posix())
    except (
        ForgeError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        SyntaxError,
        yaml.YAMLError,
    ) as exc:
        errors.append(str(exc))
    return {
        "passed": not errors,
        "errors": errors,
        "checks": ["skill-spec", "artifact-integrity", "dependency", "static-security", "schemas"],
        "note": "Static checks are conservative heuristics; the WASM boundary is mandatory",
    }
