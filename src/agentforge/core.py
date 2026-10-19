"""Trusted data handling. No generated Python is imported or executed."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_FILE = 1_000_000


class ForgeError(Exception):
    """An actionable input, validation or safety error."""


def artifact_destination(path: Path, name: str):
    if path.exists() or path.is_symlink() or path.name != name:
        raise ForgeError("Destination must be a new directory matching the Skill name")
    if any((parent / "manifest.json").is_file() for parent in path.resolve().parents):
        raise ForgeError("Do not create candidates inside an existing immutable Skill")


def strict_json(text: str | bytes) -> Any:
    def invalid(value):
        raise ValueError("Non-finite JSON number is forbidden")

    return json.loads(text, parse_constant=invalid)


def json_equal(left: Any, right: Any) -> bool:
    """JSON equality with booleans distinct from numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if re.fullmatch(
                r"(?i)(.*secret.*|.*password.*|(?:access_|refresh_|auth_)?token|api[_-]?key|authorization|credential)",
                k,
            )
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?i)\b(?:sk-[\w-]{8,}|gh[pousr]_[\w]{8,}|AKIA[A-Z0-9]{16})\b", "[REDACTED]", value
        )
        return re.sub(
            r"(?i)((?:password|token|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value
        )
    return value


def write_json(path: Path, data: Any, *, safe: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(redact(data) if safe else data, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ForgeError(f"Not a bounded regular JSON file: {path}")
    try:
        return strict_json(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ForgeError(f"Invalid JSON: {path}: {exc}") from exc


def files(root: Path) -> list[Path]:
    if (
        root.is_symlink()
        or (hasattr(root, "is_junction") and root.is_junction())
        or not root.is_dir()
    ):
        raise ForgeError("Skill must be a regular directory")
    result = []
    size = 0
    count = 0
    for path in root.rglob("*"):
        count += 1
        if count > 256:
            raise ForgeError("Skill artifact exceeds directory entry limit")
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ForgeError("Links/junctions are not allowed in Skill artifacts")
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_file():
            size += path.stat().st_size
            if path.stat().st_size > MAX_FILE or size > 4_000_000:
                raise ForgeError("Skill artifact exceeds size limit")
            result.append(path)
        if len(result) > 100:
            raise ForgeError("Skill artifact exceeds file limit")
    return sorted(result)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in files(root):
        name = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big") + name)
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()
