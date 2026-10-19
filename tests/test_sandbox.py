import hashlib
import random
import re
import subprocess

import pytest
import wasmtime

from agentforge.core import ForgeError, read_json, write_json
from agentforge.sandbox import Sandbox
from agentforge.testing import evaluate


def wasm(text):
    return bytes(wasmtime.wat2wasm(text))


def test_no_host_filesystem_network_or_environment_imports():
    for module, name in [
        ("wasi_snapshot_preview1", "path_open"),
        ("env", "getenv"),
        ("env", "socket"),
        ("env", "host_exec"),
    ]:
        result = Sandbox().execute(wasm(f'(module (import "{module}" "{name}" (func)))'), [])
        assert result["status"] == "blocked"
        assert "imports are forbidden" in result["error"]


def test_infinite_loop_fuel_traps():
    result = Sandbox(fuel=1000).execute(
        wasm("""(module
      (memory (export "memory") 1 1)
      (func (export "clean") (param i32) (result i32)
        (loop $forever (br $forever)) i32.const 0))"""),
        [{"text": ""}],
    )
    assert result["status"] == "completed"
    assert not result["results"][0]["ok"]
    assert "fuel" in result["results"][0]["error"]


def test_start_function_fuel_traps():
    result = Sandbox(fuel=1000).execute(
        wasm("""(module
      (func $start (loop $forever (br $forever))) (start $start))"""),
        [{"text": ""}],
    )
    assert not result["results"][0]["ok"]
    assert "fuel" in result["results"][0]["error"]


def test_memory_limit_and_zero_tables():
    for wat in [
        '(module (memory (export "memory") 2))',
        '(module (memory (export "memory") 1) (table 1 funcref))',
    ]:
        result = Sandbox().execute(wasm(wat), [{"text": ""}])
        assert not result["results"][0]["ok"]


def test_out_of_bounds_guest_access_traps():
    result = Sandbox().execute(
        wasm("""(module
      (memory (export "memory") 1 1)
      (func (export "clean") (param i32) (result i32)
        (i32.load (i32.const 65535))))"""),
        [{"text": ""}],
    )
    assert not result["results"][0]["ok"]
    assert "out of bounds" in result["results"][0]["error"]


def test_output_length_rejected():
    result = Sandbox().execute(
        wasm("""(module
      (memory (export "memory") 1 1)
      (func (export "clean") (param i32) (result i32) i32.const 32769))"""),
        [{"text": ""}],
    )
    assert not result["results"][0]["ok"]
    assert "ABI bounds" in result["results"][0]["error"]


def test_oversize_request_and_bad_limits():
    with pytest.raises(ForgeError):
        Sandbox().execute(b"x" * 100001, [])
    with pytest.raises(ForgeError):
        Sandbox(fuel=0)


def test_worker_wall_clock_watchdog():
    result = Sandbox(timeout=0.00001).execute(wasm("(module)"), [])
    assert result["status"] == "blocked"
    assert result["exit_code"] is None
    assert result["error"] == "TimeoutExpired"


def test_corrupt_module_fails_closed(make_skill):
    root = make_skill()
    (root / "scripts/clean.wasm").write_bytes(b"not wasm")
    manifest = read_json(root / "manifest.json")
    manifest["sha256"] = hashlib.sha256(b"not wasm").hexdigest()
    write_json(root / "manifest.json", manifest)
    report = evaluate(root)
    assert report["status"] == "blocked"
    assert not report["cases"]


def test_artifact_symlink_refusal(make_skill, tmp_path):
    root = make_skill()
    try:
        (root / "link").symlink_to(tmp_path / "outside")
    except OSError:
        pytest.skip("Windows requires symlink privilege for this filesystem probe")
    with pytest.raises(ForgeError, match="Links"):
        evaluate(root)


def test_differential_text_cleaning_real_wasm(make_skill):
    root = make_skill()
    randomizer = random.Random(20261019)
    alphabet = " ABCxyz\t\n\r\v\f你好😀\u00a0"
    texts = [
        "".join(randomizer.choice(alphabet) for _ in range(randomizer.randrange(200)))
        for _ in range(80)
    ]
    result = Sandbox().execute(
        (root / "scripts/clean.wasm").read_bytes(), [{"text": text} for text in texts]
    )
    assert result["status"] == "completed"
    for text, actual in zip(texts, result["results"], strict=True):
        expected = re.sub(r"[ \t\r\n\v\f]+", " ", text).strip(" ")
        assert actual["ok"] and actual["output"] == {"text": expected}


def test_worker_does_not_inherit_host_secrets(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_SECRET_CANARY", "private-value")
    original = subprocess.Popen
    observed = []

    def observe(*args, **kwargs):
        assert "AGENTFORGE_SECRET_CANARY" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        observed.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", observe)
    result = Sandbox().execute(wasm("(module)"), [])
    assert result["status"] == "completed"
    assert observed
