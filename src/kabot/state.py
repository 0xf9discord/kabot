"""Small persistent per-user store. No Kakao credentials or transcripts are stored."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteStore:
    """Each operation owns its connection, so sync handlers can use worker threads.

    File-backed only. A read/modify/write with get/set is not atomic; use increment for counters.
    """

    def __init__(self, path: str | Path = "kabot.sqlite3"):
        self.path = str(Path(path).resolve())
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS state (scope TEXT, key TEXT, value TEXT, "
                "expires REAL, PRIMARY KEY(scope,key))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def get(self, scope: str, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute(
                "SELECT value, expires FROM state WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
        if row is None or (row[1] is not None and row[1] <= time.time()):
            return default
        return json.loads(row[0])

    def set(self, scope: str, key: str, value: Any, *, ttl: float | None = None) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        expires = time.time() + ttl if ttl is not None else None
        with self._connect() as db:
            db.execute(
                "INSERT INTO state VALUES(?,?,?,?) ON CONFLICT(scope,key) DO UPDATE "
                "SET value=excluded.value, expires=excluded.expires",
                (scope, key, encoded, expires),
            )

    def delete(self, scope: str, key: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM state WHERE scope=? AND key=?", (scope, key))

    def increment(self, scope: str, key: str, amount: int = 1) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT value,expires FROM state WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
            current = json.loads(row[0]) if row and (row[1] is None or row[1] > time.time()) else 0
            if type(current) is not int or type(amount) is not int:
                raise ValueError("increment requires integer values")
            value = current + amount
            expires = row[1] if row and (row[1] is None or row[1] > time.time()) else None
            db.execute(
                "INSERT INTO state VALUES(?,?,?,?) ON CONFLICT(scope,key) DO UPDATE "
                "SET value=excluded.value, expires=excluded.expires",
                (scope, key, json.dumps(value), expires),
            )
            return value

    def purge_expired(self) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM state WHERE expires <= ?", (time.time(),)).rowcount
