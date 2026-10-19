from pathlib import Path

import yaml


def test_workflow_commands_are_strings_and_job_references_exist():
    root = Path(__file__).resolve().parents[1] / ".github/workflows"
    for path in root.glob("*.yml"):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        assert workflow["on"]
        assert workflow["jobs"]
        for name, job in workflow["jobs"].items():
            for step in job["steps"]:
                if "run" in step:
                    assert isinstance(step["run"], str), (path, name, step)
                    assert step["run"].strip()
            needs = job.get("needs", [])
            if isinstance(needs, str):
                needs = [needs]
            assert set(needs) <= set(workflow["jobs"]), path
