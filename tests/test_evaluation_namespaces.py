from pathlib import Path

from agentforge.artifacts import BundleGenerator
from agentforge.core import read_json, write_json
from agentforge.testing import evaluate


def test_generated_case_cannot_collide_with_engine_or_independent_labels(tmp_path):
    fixtures = Path(__file__).resolve().parents[1] / "examples/v02"
    bundle = read_json(fixtures / "integer-stats.bundle.json")
    import json

    item = next(f for f in bundle["files"] if f["path"] == "tests/cases.json")
    cases = json.loads(item["content"])
    cases[0]["id"] = "example-integration"
    item["content"] = json.dumps(cases)
    root = BundleGenerator(bundle).generate(
        read_json(fixtures / "integer-stats.plan.json"), tmp_path / "integer-stats"
    )
    held = read_json(fixtures / "integer-stats.evaluation.json")
    held["cases"][0]["id"] = "example-integration"
    path = tmp_path / "evaluation.json"
    write_json(path, held)
    report = evaluate(root, evaluation_path=path)
    assert report["status"] == "passed"
    assert len({c["id"] for c in report["cases"]}) == len(report["cases"])
    assert sum(c["original_id"] == "example-integration" for c in report["cases"]) == 3
    # Regression history remains reusable, including namespaced previous labels.
    assert (
        evaluate(root, evaluation_path=path, regression_cases=report["cases"])["status"] == "passed"
    )
