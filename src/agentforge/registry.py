"""SQLite metadata plus immutable content snapshots and local Git history."""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from .core import ForgeError, files, read_json, redact, tree_hash

_UNSET = object()


class Registry:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.git_dir = self.home / "history"
        self.db = self.home / "registry.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS versions (
                  name TEXT NOT NULL, version TEXT NOT NULL, hash TEXT NOT NULL,
                  source TEXT NOT NULL, dependencies TEXT NOT NULL, compatibility TEXT NOT NULL,
                  status TEXT NOT NULL, report TEXT NOT NULL, artifact TEXT NOT NULL,
                  git_commit TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY(name,version));
                CREATE TABLE IF NOT EXISTS active (name TEXT PRIMARY KEY, version TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def git(self, *args: str) -> str:
        executable = shutil.which("git")
        if not executable:
            raise ForgeError("Local Git executable unavailable")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            result = subprocess.run(
                [
                    executable,
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.longpaths=true",
                    "-c",
                    "user.name=AgentForge",
                    "-c",
                    "user.email=local@agentforge.invalid",
                    *args,
                ],
                cwd=self.git_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ForgeError("Local Git snapshots unavailable: " + type(exc).__name__) from exc
        if result.returncode:
            raise ForgeError("Git snapshot failed: " + result.stderr[:1000])
        return result.stdout.strip()

    def _snapshot(self, digest: str, artifact: dict) -> str:
        self.git_dir.mkdir(exist_ok=True)
        if not (self.git_dir / ".git").exists():
            self.git("init")
        relative = f"artifacts/{digest}.json"
        path = self.git_dir / relative
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
            self.git("add", "--", relative)
            self.git("commit", "-m", "Snapshot " + digest, "--", relative)
        return self.git("log", "-1", "--format=%H", "--", relative)

    def register(self, root: Path, report: dict) -> dict:
        from .validation import inspect_skill

        digest = tree_hash(root)
        if digest != report["artifact_hash"] or not inspect_skill(root)["passed"]:
            raise ForgeError("Artifact changed after evaluation or static validation failed")
        manifest = read_json(root / "manifest.json")
        artifact = {
            p.relative_to(root).as_posix(): base64.b64encode(p.read_bytes()).decode()
            for p in files(root)
        }
        if report["status"] == "passed" and (
            not report.get("execution") or report["execution"].get("status") != "completed"
        ):
            raise ForgeError("Passing registration requires execution evidence")
        status = "verified" if report["status"] == "passed" else "rejected"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM versions WHERE name=? AND version=?",
                (manifest["name"], manifest["version"]),
            ).fetchone():
                raise ForgeError(
                    "Version already registered; stable versions cannot be overwritten"
                )
            commit = self._snapshot(digest, artifact)
            db.execute(
                "INSERT INTO versions(name,version,hash,source,dependencies,compatibility,status,report,artifact,git_commit) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    manifest["name"],
                    manifest["version"],
                    digest,
                    manifest["source"],
                    json.dumps(manifest["dependencies"]),
                    manifest["compatibility"],
                    status,
                    json.dumps(redact(report)),
                    json.dumps(artifact),
                    commit,
                ),
            )
        return self.show(manifest["name"], manifest["version"])

    def list(self, query: str = "") -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT name,version,hash,source,dependencies,compatibility,status,git_commit,created FROM versions WHERE instr(name,?) > 0 ORDER BY name,created,version",
                (query,),
            ).fetchall()
            active = {r["name"]: r["version"] for r in db.execute("SELECT * FROM active")}
        return [{**dict(row), "active": active.get(row["name"]) == row["version"]} for row in rows]

    def show(self, name: str, version: str | None = None) -> dict:
        with self.connect() as db:
            if version is None:
                active = db.execute("SELECT version FROM active WHERE name=?", (name,)).fetchone()
                if not active:
                    raise ForgeError("No active version for " + name)
                version = active["version"]
            row = db.execute(
                "SELECT * FROM versions WHERE name=? AND version=?", (name, version)
            ).fetchone()
        if row is None:
            raise ForgeError("Version not found")
        result = dict(row)
        result.pop("artifact")
        result["report"] = json.loads(result["report"])
        result["dependencies"] = json.loads(result["dependencies"])
        return result

    def activate(
        self,
        name: str,
        version: str,
        *,
        rollback: bool = False,
        expected_active: str | None | object = _UNSET,
    ) -> dict:
        row = self.show(name, version)
        if row["status"] != "verified":
            raise ForgeError("Only independently verified versions may be activated")
        # Both activation and rollback re-read immutable Git evidence.
        artifact = json.loads(
            self.git("show", row["git_commit"] + ":artifacts/" + row["hash"] + ".json")
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute(
                "SELECT artifact FROM versions WHERE name=? AND version=?", (name, version)
            ).fetchone()
            if artifact != json.loads(stored["artifact"]):
                raise ForgeError("Git/SQLite snapshot integrity mismatch")
            active = db.execute("SELECT version FROM active WHERE name=?", (name,)).fetchone()
            if (
                expected_active is not _UNSET
                and (active["version"] if active else None) != expected_active
            ):
                raise ForgeError("Active version changed during evaluation; promotion refused")
            if active and not rollback:
                raise ForgeError("Active version exists; use evaluated evolve or explicit rollback")
            db.execute(
                "INSERT INTO active(name,version) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET version=excluded.version",
                (name, version),
            )
        return {
            "name": name,
            "active_version": version,
            "git_commit": row["git_commit"],
            "operation": "rollback" if rollback else "activate",
        }

    def export(self, name: str, version: str | None, destination: Path) -> Path:
        row = self.show(name, version)
        if destination.exists() or destination.name != name:
            raise ForgeError("Export requires a new directory matching the Skill name")
        artifact = json.loads(
            self.git("show", row["git_commit"] + ":artifacts/" + row["hash"] + ".json")
        )
        destination.mkdir(parents=True)
        for relative, data in artifact.items():
            path = destination / relative
            if Path(relative).is_absolute() or not path.resolve().is_relative_to(
                destination.resolve()
            ):
                raise ForgeError("Unsafe snapshot path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(data, validate=True))
        if tree_hash(destination) != row["hash"]:
            raise ForgeError("Exported snapshot hash mismatch")
        return destination
