"""Atomic, durable, operator-owned model reservations shared across CLI processes."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

from .core import ForgeError, redact

APP_ID = 0x41464247
SCALE = Decimal(1_000_000_000)  # integer nano-dollars, rounded up on reservation


def units(value) -> int:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ForgeError("Budget amount must be numeric") from exc
    if not number.is_finite() or number < 0 or number > 1_000_000:
        raise ForgeError("Budget amount must be finite, non-negative and <= 1000000 USD")
    return int((number * SCALE).to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    def __init__(self, directory: Path):
        directory = Path(directory).absolute()
        for path in [directory, *directory.parents]:
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ForgeError("Budget state cannot use links or junctions")
            if (path / "manifest.json").is_file():
                raise ForgeError("Budget state must be outside Skill artifacts")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            info = directory.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ForgeError("Budget directory must be private and owned by the operator")
        self.db = directory / "budgets.sqlite3"
        if self.db.is_symlink() or (hasattr(self.db, "is_junction") and self.db.is_junction()):
            raise ForgeError("Budget database cannot be a link or junction")
        try:
            fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(self.connect()) as conn:
            app = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app not in (0, APP_ID) or (app == 0 and tables):
                raise ForgeError("Selected state is not an AgentForge budget ledger")
            if app == APP_ID and conn.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ForgeError("Unsupported budget ledger schema; refusing to downgrade")
            conn.executescript(f"""
                PRAGMA application_id={APP_ID};
                CREATE TABLE IF NOT EXISTS accounts (
                    name TEXT PRIMARY KEY, money INTEGER NOT NULL, tokens INTEGER NOT NULL,
                    requests INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(name),
                    request_hash TEXT NOT NULL, model TEXT NOT NULL, state TEXT NOT NULL,
                    money INTEGER NOT NULL, tokens INTEGER NOT NULL,
                    held_money INTEGER NOT NULL, held_tokens INTEGER NOT NULL,
                    created REAL NOT NULL, receipt_hash TEXT, note TEXT
                );
                CREATE TABLE IF NOT EXISTS reconciliations (
                    id INTEGER PRIMARY KEY, reservation TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL, previous_money INTEGER NOT NULL,
                    actual_money INTEGER NOT NULL, actual_tokens INTEGER NOT NULL,
                    note TEXT NOT NULL, created REAL NOT NULL
                );
                PRAGMA user_version=1;
            """)

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create(self, account: str, *, dollars, tokens: int, requests: int):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", account):
            raise ForgeError("Budget account must be a bounded plain identifier")
        if redact(account) != account:
            raise ForgeError("Budget account cannot contain sensitive values")
        if (
            type(tokens) is not int
            or type(requests) is not int
            or not (1 <= tokens <= 1_000_000_000 and 1 <= requests <= 1_000_000)
        ):
            raise ForgeError("Invalid persistent token/request limits")
        with closing(self.connect()) as conn:
            try:
                conn.execute(
                    "INSERT INTO accounts VALUES (?,?,?,?)",
                    (account, units(dollars), tokens, requests),
                )
            except sqlite3.IntegrityError as exc:
                raise ForgeError("Budget account exists; limits cannot silently increase") from exc
        return self.status(account)

    @staticmethod
    def totals(conn, account):
        row = conn.execute(
            "SELECT COALESCE(SUM(held_money),0), COALESCE(SUM(held_tokens),0), "
            "COUNT(*) FROM reservations WHERE account=?",
            (account,),
        ).fetchone()
        return tuple(row)

    def reserve(self, account: str, *, amount, tokens: int, request_hash: str, model: str) -> str:
        money = units(amount)
        if not isinstance(model, str) or not 1 <= len(model) <= 100:
            raise ForgeError("Model identifier must be a bounded string")
        model = redact(model)
        if (
            type(tokens) is not int
            or tokens <= 0
            or not re.fullmatch(r"[a-f0-9]{64}", request_hash)
        ):
            raise ForgeError("Invalid durable reservation")
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            policy = conn.execute("SELECT * FROM accounts WHERE name=?", (account,)).fetchone()
            if not policy:
                raise ForgeError("Explicit persistent budget account has not been initialized")
            spent, used, count = self.totals(conn, account)
            if (
                spent + money > policy["money"]
                or used + tokens > policy["tokens"]
                or count + 1 > policy["requests"]
            ):
                raise ForgeError("Persistent budget exhausted; no request sent")
            ident = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (
                    ident,
                    account,
                    request_hash,
                    model,
                    "reserved",
                    money,
                    tokens,
                    money,
                    tokens,
                    time.time(),
                ),
            )
            conn.commit()  # MUST precede transport: a crash leaves the reservation intact.
        return ident

    def finish(self, ident: str, *, amount, tokens: int, receipt: bytes):
        money = units(amount)
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM reservations WHERE id=?", (ident,)).fetchone()
            if not row or row["state"] != "reserved":
                raise ForgeError("Reservation is absent or already finalized")
            if (
                type(tokens) is not int
                or tokens < 0
                or money > row["money"]
                or tokens > row["tokens"]
            ):
                conn.execute("UPDATE reservations SET state='unknown' WHERE id=?", (ident,))
                conn.commit()
                raise ForgeError("Actual usage exceeds reservation; reconciliation required")
            conn.execute(
                "UPDATE reservations SET state='completed',held_money=?,held_tokens=?,"
                "receipt_hash=? WHERE id=?",
                (money, tokens, hashlib.sha256(receipt).hexdigest(), ident),
            )
            conn.commit()

    def unknown(self, ident: str):
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE reservations SET state='unknown' WHERE id=? AND state='reserved'", (ident,)
            )

    def reconcile(self, ident: str, *, amount, tokens: int, receipt: bytes, note: str):
        """Explicit operator accounting, never an automatic retry/refund."""
        if not 1 <= len(note) <= 500 or not receipt or len(receipt) > 1_000_000:
            raise ForgeError("Reconciliation needs bounded nonempty provider evidence and note")
        money = units(amount)
        if type(tokens) is not int or tokens < 0 or tokens > 1_000_000_000:
            raise ForgeError("Invalid actual token accounting")
        digest = hashlib.sha256(receipt).hexdigest()
        note = redact(note)
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM reservations WHERE id=?", (ident,)).fetchone()
            if not row or row["state"] not in {"reserved", "unknown"}:
                raise ForgeError("Only an unresolved reservation can be reconciled")
            conn.execute(
                "INSERT INTO reconciliations VALUES (NULL,?,?,?,?,?,?,?)",
                (ident, digest, row["held_money"], money, tokens, note, time.time()),
            )
            conn.execute(
                "UPDATE reservations SET state='reconciled',held_money=?,held_tokens=?,"
                "receipt_hash=?,note=? WHERE id=?",
                (money, tokens, digest, note, ident),
            )
            conn.commit()
        return {"id": ident, "state": "reconciled", "receipt_sha256": digest}

    def status(self, account: str) -> dict:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM accounts WHERE name=?", (account,)).fetchone()
            if not row:
                raise ForgeError("Budget account does not exist")
            money, tokens, requests = self.totals(conn, account)
            pending = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,model,state,held_money,held_tokens,created "
                    "FROM reservations WHERE account=? AND state IN ('reserved','unknown')",
                    (account,),
                )
            ]
        return {
            "account": account,
            "limit_usd": str(Decimal(row["money"]) / SCALE),
            "charged_or_held_usd": str(Decimal(money) / SCALE),
            "remaining_usd": str(Decimal(row["money"] - money) / SCALE),
            "tokens_charged_or_held": tokens,
            "token_limit": row["tokens"],
            "requests": requests,
            "request_limit": row["requests"],
            "unresolved": pending,
        }

    def history(self, account: str) -> list[dict]:
        self.status(account)
        with closing(self.connect()) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM reservations WHERE account=? ORDER BY created DESC LIMIT 1000",
                    (account,),
                )
            ]
