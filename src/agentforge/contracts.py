"""Bounded local JSON Schema contracts; remote resolution is never permitted."""

import hashlib
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .core import ForgeError


def check_schema(schema: dict) -> None:
    if not isinstance(schema, dict) or len(json.dumps(schema)) > 16000:
        raise ForgeError("Schema must be a bounded JSON object")

    def walk(value, depth=0):
        if depth > 24:
            raise ForgeError("Schema nesting limit exceeded")
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    "$ref",
                    "$dynamicRef",
                    "$recursiveRef",
                    "$id",
                    "pattern",
                    "patternProperties",
                    "allOf",
                    "anyOf",
                    "oneOf",
                    "not",
                    "if",
                    "then",
                    "else",
                    "uniqueItems",
                    "dependentSchemas",
                    "unevaluatedProperties",
                    "unevaluatedItems",
                }:
                    raise ForgeError("Schema references, regex and remote identifiers are disabled")
                if key in {"properties", "$defs", "definitions"} and isinstance(child, dict):
                    for nested in child.values():
                        walk(nested, depth + 1)
                elif key not in {"const", "enum", "default", "examples", "title", "description"}:
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ForgeError("Invalid local JSON Schema") from exc


def contract_hash(spec: dict) -> str:
    data = {k: spec[k] for k in ("name", "kind", "inputs", "outputs")}
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_cases(cases: list, spec: dict) -> None:
    if not isinstance(cases, list) or not 1 <= len(cases) <= 128:
        raise ForgeError("Require 1..128 bounded behavioral cases")
    identifiers = set()
    input_validator = Draft202012Validator(spec["inputs"])
    output_validator = Draft202012Validator(spec["outputs"])
    for case in cases:
        if (
            not isinstance(case, dict)
            or "input" not in case
            or not isinstance(case.get("id"), str)
            or not 1 <= len(case["id"]) <= 160
            or case["id"] in identifiers
        ):
            raise ForgeError("Cases require unique bounded IDs and inputs")
        identifiers.add(case["id"])
        if ("expected" in case) == ("error_type" in case) or (
            "error_type" in case and case["error_type"] != "ValidationError"
        ):
            raise ForgeError("Cases require expected output or a schema ValidationError")
        valid_input = input_validator.is_valid(case["input"])
        if "error_type" in case and valid_input:
            raise ForgeError("ValidationError cases must actually violate the input schema")
        if "expected" in case and (
            not valid_input or not output_validator.is_valid(case["expected"])
        ):
            raise ForgeError("Successful case inputs/outputs must conform to the sealed schemas")
        if len(json.dumps(case, allow_nan=False).encode()) > 65000:
            raise ForgeError("Case exceeds byte budget")
