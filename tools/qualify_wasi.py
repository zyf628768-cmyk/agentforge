"""Run real CPython/WASI Skills and hostile probes with an explicit approved runtime.

No model requests and no native execution of generated source. Evidence is written
even on assertion failure. The runtime must be provisioned separately.
"""

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

from agentforge.artifacts import BundleGenerator
from agentforge.core import read_json, tree_hash, write_json
from agentforge.evolution import Budget, evolve
from agentforge.python_wasi import PythonWasi
from agentforge.registry import Registry
from agentforge.testing import evaluate

FIXTURES = Path(__file__).resolve().parents[1] / "examples/v02"

PROBE = """import json, os, sys
mode = json.load(sys.stdin)["mode"]
if mode == "environment":
    result = dict(os.environ)
elif mode == "infinite":
    while True: pass
elif mode == "sleep":
    import time
    time.sleep(60)
elif mode == "memory":
    value = bytearray(128*1024*1024)
    result = "escaped"
elif mode == "flood":
    sys.stdout.write("x"*200000)
    result = "escaped"
else:
    try:
        if mode == "host-read":
            open("/etc/passwd").read()
        elif mode == "skill-write":
            open("/skill/scripts/escaped.txt", "w").write("escaped")
        elif mode == "runtime-write":
            open("/runtime/escaped.txt", "w").write("escaped")
        elif mode == "traversal":
            open("/skill/../../etc/passwd").read()
        elif mode == "network":
            import socket
            connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            connection.connect(("127.0.0.1", 9))
        elif mode == "process":
            import subprocess
            subprocess.run(["/bin/sh", "-c", "true"], check=True)
        else:
            raise AssertionError(mode)
        result = "escaped"
    except (OSError, ImportError, NotImplementedError) as exc:
        result = {"denied": True, "type": type(exc).__name__}
json.dump(result, sys.stdout)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")
    args.output.mkdir(parents=True)
    runtime = PythonWasi(
        runtime_dir=args.runtime_dir, manifest_sha256=args.manifest_sha256, timeout=30
    )
    config = {
        "backend": "python-wasi",
        "runtime_dir": str(args.runtime_dir.resolve()),
        "manifest_sha256": args.manifest_sha256,
    }
    evidence = {
        "platform": platform.platform(),
        "python": sys.version,
        "command": sys.argv,
        "paid_api_calls": 0,
        "checks": {},
        "status": "failed",
    }
    started = time.monotonic()
    try:
        evidence["policy"] = runtime.preflight()
        spec = read_json(FIXTURES / "csv-summary.plan.json")
        bundle = read_json(FIXTURES / "csv-summary.bundle.json")
        root = BundleGenerator(bundle).generate(spec, args.output / "stable/csv-summary")
        independent = FIXTURES / "csv-summary.evaluation.json"
        report = evaluate(
            root, args.output / "csv.json", evaluation_path=independent, container_config=config
        )
        assert report["status"] == "passed", report["execution"]
        evidence["checks"]["real_csv_skill"] = report["metrics"]
        helper_bundle = json.loads(json.dumps(bundle))
        helper_bundle["files"][0]["path"] = "scripts/summary_impl.py"
        helper_bundle["files"].append(
            {"path": "scripts/main.py", "content": "import summary_impl\n"}
        )
        helper_root = BundleGenerator(helper_bundle).generate(
            spec, args.output / "helper/csv-summary"
        )
        helper_report = evaluate(
            helper_root,
            args.output / "helper.json",
            evaluation_path=independent,
            container_config=config,
        )
        assert helper_report["status"] == "passed", helper_report
        evidence["checks"]["readonly_multi_module_python"] = True
        baseline_hash = tree_hash(root)
        registry = Registry(args.output / "registry")
        registry.register(root, report)
        registry.activate(spec["name"], spec["version"])
        broken_bundle = json.loads(json.dumps(bundle))
        broken_bundle["files"][0]["content"] = broken_bundle["files"][0]["content"].replace(
            '"sum": sum(numbers)', '"sum": sum(numbers) + 1'
        )
        broken = BundleGenerator(broken_bundle).generate(spec, args.output / "broken/csv-summary")
        repair = evolve(
            broken,
            args.output / "repair",
            registry,
            generator=BundleGenerator(bundle),
            evaluation_path=independent,
            container_config=config,
            budget=Budget(1, 120, 0),
        )
        assert repair["accepted"], repair
        evidence["checks"]["real_python_repair"] = repair
        active_hash = registry.show(spec["name"])["hash"]
        repaired = Path(repair["attempts"][0]["path"])
        regression = evolve(
            repaired,
            args.output / "regression",
            registry,
            mode="optimize",
            generator=BundleGenerator(broken_bundle),
            evaluation_path=independent,
            container_config=config,
            budget=Budget(1, 120, 0),
        )
        assert not regression["accepted"] and regression["attempts"], regression
        assert registry.show(spec["name"])["hash"] == active_hash
        assert tree_hash(root) == baseline_hash
        evidence["checks"]["regression_rejected_old_version_preserved"] = regression
        probe = args.output / "hostile-probes"
        (probe / "scripts").mkdir(parents=True)
        (probe / "scripts/main.py").write_text(PROBE, encoding="utf-8")
        dummy_name = "AGENTFORGE_PUBLIC_DUMMY_CANARY"
        os.environ[dummy_name] = "not-a-real-secret"
        modes = [
            "environment",
            "host-read",
            "skill-write",
            "runtime-write",
            "traversal",
            "network",
            "process",
            "memory",
            "flood",
            "infinite",
        ]
        hostile = runtime.execute(
            probe, [{"mode": m} for m in modes], {"inputs": {}, "outputs": {}}
        )
        write_json(args.output / "hostile.json", hostile, safe=True)
        assert hostile["status"] == "completed", hostile
        for mode, result in zip(modes, hostile["results"], strict=True):
            if mode == "environment":
                assert result["ok"] and dummy_name not in result["output"]
                assert set(result["output"]) <= {"LANG"}, result
            elif mode in {"memory", "flood", "infinite"}:
                assert not result["ok"], (mode, result)
            else:
                assert result["ok"] and result["output"].get("denied"), (mode, result)
        del os.environ[dummy_name]
        assert not (probe / "scripts/escaped.txt").exists()
        assert not (args.runtime_dir / "escaped.txt").exists()
        evidence["checks"]["hostile_capabilities_denied"] = modes
        sleeper = PythonWasi(
            runtime_dir=args.runtime_dir, manifest_sha256=args.manifest_sha256, timeout=10
        )
        sleep = sleeper.execute(probe, [{"mode": "sleep"}], {"inputs": {}, "outputs": {}})
        write_json(args.output / "wall-timeout.json", sleep, safe=True)
        assert sleep["status"] == "blocked" and sleep["error"] == "TimeoutExpired", sleep
        evidence["checks"]["blocking_wasi_call_wall_timeout"] = True
        runtime.preflight()  # All sealed runtime files still match after attacks.
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["error"] = str(exc)
        raise
    finally:
        evidence["seconds"] = time.monotonic() - started
        write_json(args.output / "qualification.json", evidence, safe=True)
        print(
            json.dumps(
                {
                    "status": evidence["status"],
                    "checks": list(evidence["checks"]),
                    "report": str(args.output / "qualification.json"),
                }
            )
        )


if __name__ == "__main__":
    main()
