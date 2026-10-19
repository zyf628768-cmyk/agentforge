"""For use by a reviewer after auditing; engine uses JSON cases directly."""
from pathlib import Path
from agentforge.testing import evaluate

def test_skill():
    report = evaluate(Path(__file__).resolve().parents[1])
    assert report["status"] == "passed", report
