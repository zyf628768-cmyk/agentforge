"""Durable container leases, supervised independently of the calling CLI.

The directory and supervisor are operator-owned trusted state, never mounted into
a guest. A lease is committed before Docker create, using a preselected name so a
crash between daemon creation and its response cannot lose the container identity.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from .core import ForgeError

APP_ID = 0x41464C53


def boot_identity() -> str:
    if os.sys.platform.startswith("linux"):
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    # Unit/protocol testing on Windows; production Python guests require Linux.
    return "non-linux-test-host"


class LeaseStore:
    def __init__(self, directory: Path, policy: str):
        directory = Path(directory).absolute()
        for path in [directory, *directory.parents]:
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ForgeError("Lease state cannot use links/junctions")
            if (path / "manifest.json").is_file():
                raise ForgeError("Lease state must be outside immutable Skill artifacts")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            info = directory.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ForgeError("Lease directory must be private and owned by the current user")
        self.directory = directory.resolve()
        self.policy = hashlib.sha256(policy.encode()).hexdigest()
        self.db = self.directory / "leases.sqlite3"
        if self.db.is_symlink():
            raise ForgeError("Lease database cannot be a link")
        try:
            descriptor = os.open(self.db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            os.close(descriptor)
        with closing(self.connect()) as conn:
            application = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if application != APP_ID and (application != 0 or tables):
                raise ForgeError("Selected database is not an AgentForge lease database")
            conn.executescript(f"""
                PRAGMA application_id={APP_ID};
                CREATE TABLE IF NOT EXISTS leases (
                    name TEXT PRIMARY KEY, policy TEXT NOT NULL, boot TEXT NOT NULL,
                    expires_wall REAL NOT NULL, expires_mono REAL NOT NULL,
                    state TEXT NOT NULL, last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS supervisors (
                    policy TEXT PRIMARY KEY, owner TEXT NOT NULL, pid INTEGER NOT NULL,
                    boot TEXT NOT NULL, wall REAL NOT NULL, mono REAL NOT NULL
                );
            """)

    def connect(self):
        connection = sqlite3.connect(self.db, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def heartbeat(self, owner: str, *, takeover_after: float = 5) -> None:
        wall, mono, boot = time.time(), time.monotonic(), boot_identity()
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT * FROM supervisors WHERE policy=?", (self.policy,)
            ).fetchone()
            if (
                previous
                and previous["owner"] != owner
                and previous["boot"] == boot
                and 0 <= mono - previous["mono"] < takeover_after
            ):
                raise ForgeError("Another live supervisor already owns this policy")
            conn.execute(
                "INSERT OR REPLACE INTO supervisors VALUES (?,?,?,?,?,?)",
                (self.policy, owner, os.getpid(), boot, wall, mono),
            )
            conn.commit()

    def require_reaper(self) -> dict:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM supervisors WHERE policy=?", (self.policy,)
            ).fetchone()
        if not row or row["boot"] != boot_identity():
            raise ForgeError("Independent sandbox supervisor is unavailable")
        age = time.monotonic() - row["mono"]
        if not 0 <= age <= 3:
            raise ForgeError("Sandbox supervisor heartbeat is stale; execution refused")
        if os.name != "nt":
            try:
                os.kill(row["pid"], 0)
            except OSError as exc:
                raise ForgeError("Sandbox supervisor process is unavailable") from exc
        return {"pid": row["pid"], "heartbeat_age_seconds": age, "durable_leases": True}

    def reserve(self, seconds: float) -> str:
        if not math.isfinite(seconds) or not 0 < seconds <= 30:
            raise ForgeError("Container lease must have a finite 0..30 second lifetime")
        self.require_reaper()
        name = "agentforge-" + uuid.uuid4().hex
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO leases VALUES (?,?,?,?,?,?,NULL)",
                (
                    name,
                    self.policy,
                    boot_identity(),
                    time.time() + seconds,
                    time.monotonic() + seconds,
                    "reserved",
                ),
            )
        return name

    def update(self, name: str, state: str, error: str | None = None):
        if state not in {"created", "running", "cleanup-pending", "closed"}:
            raise ForgeError("Invalid lease state")
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE leases SET state=?, last_error=? WHERE name=? AND policy=?",
                (state, error, name, self.policy),
            )

    def outstanding(self) -> list[dict]:
        with closing(self.connect()) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM leases WHERE policy=? AND state!='closed'", (self.policy,)
                )
            ]

    def lookup(self, name: str) -> dict | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM leases WHERE name=? AND policy=?", (name, self.policy)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def is_expired(row: dict) -> bool:
        return (
            row["state"] == "cleanup-pending"
            or row["boot"] != boot_identity()
            or time.time() >= row["expires_wall"]
            or time.monotonic() >= row["expires_mono"]
        )

    def expired(self) -> list[dict]:
        return [row for row in self.outstanding() if self.is_expired(row)]

    def staging(self, name: str) -> Path:
        if not name.startswith("agentforge-") or len(name) != 43:
            raise ForgeError("Invalid lease name")
        try:
            uuid.UUID(hex=name[11:])
        except ValueError as exc:
            raise ForgeError("Invalid lease name") from exc
        return self.directory / name

    def remove_staging(self, name: str):
        target = self.staging(name)
        if target.parent.resolve() != self.directory or target.is_symlink():
            raise ForgeError("Unsafe staging cleanup path")
        if hasattr(target, "is_junction") and target.is_junction():
            raise ForgeError("Unsafe staging cleanup junction")
        if target.exists():

            def concurrent_missing(function, path, exc_info):
                if not isinstance(exc_info[1], FileNotFoundError):
                    raise exc_info[1]

            shutil.rmtree(target, onerror=concurrent_missing)


def reap(store: LeaseStore, control, inventory=()) -> dict:
    """Only leases from this policy and matching daemon labels can be removed."""
    removed, failed = [], []
    candidates = {row["name"]: row for row in store.expired()}
    # The daemon can finish create after a control-client timeout. Closed leases
    # remain as tombstones; an inventory sweep catches those late containers too.
    for name in inventory:
        row = store.lookup(name)
        if row and store.is_expired(row):
            candidates[name] = row
    for row in candidates.values():
        name = row["name"]
        try:
            if control(name):
                store.remove_staging(name)
                store.update(name, "closed")
                removed.append(name)
        except (ForgeError, OSError, ValueError) as exc:
            store.update(name, "cleanup-pending", type(exc).__name__)
            failed.append({"name": name, "error_type": type(exc).__name__})
    return {"removed": removed, "failed": failed, "outstanding": len(store.outstanding())}
