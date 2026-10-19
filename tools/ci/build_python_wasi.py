"""Build trusted CPython/WASI from pinned official sources on a disposable CI VM.

This is explicit runtime provisioning, never invoked by Skill execution.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

CPYTHON_COMMIT = "24d048d3601c2f1d41fa357897c1c91bb0a0bc13"


def build(output: Path):
    output = output.resolve()
    assert not output.exists()
    task_dir = Path("work/wasi-build").resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    provenance = {"cpython_commit": CPYTHON_COMMIT, "releases": [], "commands": []}
    log = Path("wasi-build.log").open("w", encoding="utf-8")

    def run(command, *, cwd=None, env=None):
        command = list(map(str, command))
        print("RUN " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=log, timeout=1200)
        provenance["commands"].append({"command": command, "exit_code": result.returncode})
        log.flush()
        if result.returncode:
            print(Path("wasi-build.log").read_text(encoding="utf-8")[-20000:])
            raise RuntimeError("Trusted runtime build failed; see real compiler log")

    def tool(repo, tag, match):
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        req = urllib.request.Request(url, headers={"User-Agent": "AgentForge-runtime-builder"})
        with urllib.request.urlopen(req, timeout=60) as response:
            release = json.load(response)
        choices = [a for a in release["assets"] if match(a["name"])]
        assert len(choices) == 1, [a["name"] for a in release["assets"]]
        asset = choices[0]
        assert asset["browser_download_url"].startswith(
            f"https://github.com/{repo}/releases/download/{tag}/"
        )
        digest = asset.get("digest")
        assert isinstance(digest, str) and digest.startswith("sha256:")
        archive = task_dir / asset["name"]
        with (
            urllib.request.urlopen(asset["browser_download_url"], timeout=120) as response,
            archive.open("wb") as target,
        ):
            shutil.copyfileobj(response, target)
        assert "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest() == digest
        extracted = task_dir / repo.rsplit("/", 1)[-1]
        extracted.mkdir()
        with tarfile.open(archive) as package:
            package.extractall(extracted, filter="data")
        provenance["releases"].append(
            {"repository": repo, "tag": tag, "asset": asset["name"], "digest": digest}
        )
        return next(p for p in extracted.iterdir() if p.is_dir())

    sdk = tool(
        "WebAssembly/wasi-sdk",
        "wasi-sdk-34",
        lambda name: name.startswith("wasi-sdk-34") and name.endswith("x86_64-linux.tar.gz"),
    )
    engine = tool(
        "bytecodealliance/wasmtime",
        "v49.0.0",
        lambda name: name == "wasmtime-v49.0.0-x86_64-linux.tar.xz",
    )
    source = task_dir / "cpython"
    run(["git", "init", source])
    run(
        [
            "git",
            "-C",
            source,
            "fetch",
            "--depth=1",
            "https://github.com/python/cpython.git",
            CPYTHON_COMMIT,
        ]
    )
    run(["git", "-C", source, "checkout", "--detach", "FETCH_HEAD"])
    environment = dict(
        os.environ,
        WASI_SDK_PATH=str(sdk),
        PATH=str(engine) + os.pathsep + os.environ["PATH"],
        TERM="dumb",
    )
    run(["python", "Tools/wasm/wasi.py", "build", "--quiet"], cwd=source, env=environment)
    output.mkdir()
    shutil.copyfile(source / "cross-build/wasm32-wasip1/python.wasm", output / "python.wasm")
    stdlib = output / "lib/python3.13"
    shutil.copytree(
        source / "Lib",
        stdlib,
        ignore=shutil.ignore_patterns(
            "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo"
        ),
    )
    shutil.copyfile(source / "LICENSE", output / "LICENSE.cpython")
    hashes = {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.rglob("*")
        if p.is_file()
    }
    provenance["files"] = hashes
    (output / "runtime-manifest.json").write_text(json.dumps(provenance, indent=2))
    log.close()
    print(
        json.dumps(
            {
                "status": "built",
                "module_bytes": (output / "python.wasm").stat().st_size,
                "files": len(hashes),
                "cpython_commit": CPYTHON_COMMIT,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
