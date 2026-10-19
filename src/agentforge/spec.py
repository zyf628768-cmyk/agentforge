"""Editable planning format with a deliberately bounded offline backend."""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator

from .contracts import check_schema
from .core import ForgeError, redact

INPUT_SCHEMA = {
    "type": "object",
    "required": ["text"],
    "additionalProperties": False,
    "properties": {"text": {"type": "string", "maxLength": 8192}},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["text"],
    "additionalProperties": False,
    "properties": {"text": {"type": "string"}},
}


def validate(spec: dict) -> dict:
    schema = json.loads(files("agentforge").joinpath("data/spec.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(spec), key=lambda e: str(e.path))
    if errors:
        raise ForgeError("Invalid specification: " + "; ".join(e.message for e in errors))
    if spec["kind"] == "text-cleaner" and (
        spec["inputs"] != INPUT_SCHEMA or spec["outputs"] != OUTPUT_SCHEMA
    ):
        raise ForgeError("Offline backend requires the documented text JSON contract")
    check_schema(spec["inputs"])
    check_schema(spec["outputs"])
    if redact(spec) != spec:
        raise ForgeError("Remove sensitive values before storing the specification")
    return spec


def general_plan(
    goal: str,
    name: str,
    kind: str = "wasm-json",
    *,
    inputs: dict | None = None,
    outputs: dict | None = None,
) -> dict:
    """Any goal can be specified. Generation and independent acceptance remain separate."""
    return validate(
        {
            "name": name,
            "version": "0.2.0",
            "kind": kind,
            "goal": goal,
            "inputs": inputs if inputs is not None else {},
            "outputs": outputs if outputs is not None else {},
            "dependencies": [],
            "steps": [
                "Validate local JSON input",
                "Implement the stated goal",
                "Return JSON conforming to the sealed output contract",
            ],
            "risks": ["Generated code is untrusted", "No network or host capabilities"],
            "acceptance": [
                "Pass independently authored behavioral cases",
                "Preserve prior passing behavior",
            ],
            "test_plan": ["generated", "independent", "invalid-input", "regression", "security"],
            "options": {},
        }
    )


def plan(goal: str, name: str = "text-cleaner") -> dict:
    if not any(word in goal.lower() for word in ("text", "whitespace", "文本", "空白")):
        raise ForgeError(
            "Offline builder supports text cleaning only; supply a new Generator backend"
        )
    return validate(
        {
            "name": name,
            "version": "0.1.0",
            "goal": goal,
            "kind": "text-cleaner",
            "inputs": INPUT_SCHEMA,
            "outputs": OUTPUT_SCHEMA,
            "dependencies": [],
            "steps": [
                "Validate JSON text input",
                "Trim/collapse ASCII whitespace in WASM",
                "Return UTF-8 JSON, preserving case and non-ASCII bytes",
            ],
            "risks": [
                "Generated code is untrusted",
                "Unicode whitespace is preserved",
                "No filesystem, network, environment or WASI capabilities",
            ],
            "acceptance": [
                "Collapse ASCII space/tab/CR/LF/VT/FF",
                "Preserve Unicode and case",
                "Reject non-string input",
                "Do not change an accepted artifact",
            ],
            "test_plan": [
                "unit",
                "integration",
                "invalid-input",
                "independent-holdout",
                "specification",
                "dependencies",
                "security",
            ],
            "options": {"preserve_case": True},
        }
    )
