"""Authored offline protocol fixtures, not claimed model-generated quality results."""

import json
from pathlib import Path

from agentforge.contracts import contract_hash
from agentforge.core import write_json
from agentforge.spec import general_plan


def response(output):
    return {
        "id": "offline-recording",
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 200},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(output, ensure_ascii=True)}],
            }
        ],
    }


def create(root: Path):
    directory = root / "examples/v02"
    templates = directory / "templates"
    definitions = [
        (
            "integer-stats",
            "Compute sum and count of signed integers",
            "wasm-json",
            "sum.wat",
            {
                "type": "array",
                "maxItems": 128,
                "items": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
            },
            {
                "type": "object",
                "required": ["sum", "count"],
                "additionalProperties": False,
                "properties": {"sum": {"type": "integer"}, "count": {"type": "integer"}},
            },
            [1, 2, 3],
            {"sum": 6, "count": 3},
            [{"id": "negative", "input": [-7, 2], "expected": {"sum": -5, "count": 2}}],
            [
                {
                    "id": "private-mixed",
                    "input": [-47, 13, 0, -2],
                    "expected": {"sum": -36, "count": 4},
                },
                {"id": "private-empty", "input": [], "expected": {"sum": 0, "count": 0}},
                {"id": "invalid-float", "input": [1.5], "error_type": "ValidationError"},
            ],
        ),
        (
            "rot13",
            "Apply ROT13 to ASCII letters, preserving Unicode and JSON escapes",
            "wasm-json",
            "rot13.wat",
            {"type": "string", "maxLength": 4096},
            {"type": "string"},
            "Hello 世界!",
            "Uryyb 世界!",
            [{"id": "caps", "input": "ABCxyz", "expected": "NOPklm"}],
            [
                {"id": "private-escapes", "input": 'A\n\u001f"\\😀', "expected": 'N\n\u001f"\\😀'},
                {"id": "private-empty", "input": "", "expected": ""},
                {"id": "invalid-number", "input": 3, "error_type": "ValidationError"},
            ],
        ),
        (
            "csv-summary",
            "Summarize a numeric CSV column as count, sum and mean",
            "python-json",
            "csv_summary.py",
            {
                "type": "object",
                "required": ["csv", "column"],
                "additionalProperties": False,
                "properties": {
                    "csv": {"type": "string", "maxLength": 8192},
                    "column": {"type": "string", "maxLength": 64},
                },
            },
            {
                "type": "object",
                "required": ["count", "sum", "mean"],
                "additionalProperties": False,
                "properties": {
                    "count": {"type": "integer"},
                    "sum": {"type": "number"},
                    "mean": {"type": ["number", "null"]},
                },
            },
            {"csv": "name,value\nA,2\nB,4\n", "column": "value"},
            {"count": 2, "sum": 6.0, "mean": 3.0},
            [],
            [
                {
                    "id": "private-negative",
                    "input": {"csv": "v\n-2\n5\n", "column": "v"},
                    "expected": {"count": 2, "sum": 3.0, "mean": 1.5},
                }
            ],
        ),
    ]
    for (
        name,
        goal,
        kind,
        template,
        inputs,
        outputs,
        example,
        expected,
        cases,
        independent,
    ) in definitions:
        spec = general_plan(goal, name, kind, inputs=inputs, outputs=outputs)
        entry = "scripts/main.wat" if kind == "wasm-json" else "scripts/main.py"
        bundle = {
            "files": [
                {"path": entry, "content": (templates / template).read_text(encoding="utf-8")},
                {
                    "path": "README.md",
                    "content": f"# {name}\n\n{goal}.\n\nUse agentforge run; never execute generated Python on the host.\n",
                },
                {
                    "path": "tests/cases.json",
                    "content": json.dumps(
                        [{"id": "normal", "input": example, "expected": expected}, *cases]
                    ),
                },
                {"path": "examples/input.json", "content": json.dumps(example)},
                {"path": "examples/output.json", "content": json.dumps(expected)},
            ]
        }
        write_json(directory / f"{name}.plan.json", spec)
        write_json(directory / f"{name}.bundle.json", bundle)
        write_json(directory / f"{name}.response.json", {"responses": [response(bundle)]})
        write_json(
            directory / f"{name}.planning-response.json",
            {"responses": [response({"spec_json": json.dumps(spec)})]},
        )
        write_json(
            directory / f"{name}.evaluation.json",
            {"contract_hash": contract_hash(spec), "cases": independent},
        )
        if name == "integer-stats":
            broken = json.loads(json.dumps(bundle))
            broken["files"][0]["content"] = broken["files"][0]["content"].replace(
                "(i32.mul (local.get $v) (local.get $sign))", "(local.get $v)"
            )
            write_json(directory / "integer-stats.broken.bundle.json", broken)
            write_json(
                directory / "integer-stats.broken.response.json", {"responses": [response(broken)]}
            )
    print("Created three authored generic engineering fixtures and evaluator-owned cases")


if __name__ == "__main__":
    create(Path(__file__).resolve().parents[1])
