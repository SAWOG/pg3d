from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS warnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    rule       TEXT    NOT NULL,
    reason     TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings (guild_id, user_id, created_at);
"""


class WarningStore:
    """sqlite tabanlı uyarı kaydı; bloklayan çağrılar thread'e alınır."""

    def __init__(self, path: Path, expire_days: int) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = asyncio.Lock()
        self._expire_s = expire_days * 86400

    def close(self) -> None:
        self._conn.close()

    async def _run(self, sql: str, params: tuple[object, ...]) -> list[tuple[Any, ...]]:
        def work() -> list[tuple[Any, ...]]:
            with self._conn:
                return self._conn.execute(sql, params).fetchall()

        async with self._lock:
            return await asyncio.to_thread(work)

    async def add(self, guild_id: int, user_id: int, rule: str, reason: str) -> int:
        """Uyarı ekler, süresi dolmamış toplam uyarı sayısını döndürür."""
        now = int(time.time())
        await self._run(
            "INSERT INTO warnings (guild_id, user_id, rule, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, rule, reason, now),
        )
        return await self.count(guild_id, user_id)

    async def count(self, guild_id: int, user_id: int) -> int:
        rows = await self._run(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
            (guild_id, user_id, int(time.time()) - self._expire_s),
        )
        return int(rows[0][0])

    async def list(self, guild_id: int, user_id: int, limit: int = 10) -> list[tuple[str, str, int]]:
        rows = await self._run(
            "SELECT rule, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? "
            "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, user_id, int(time.time()) - self._expire_s, limit),
        )
        return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]

    async def clear(self, guild_id: int, user_id: int) -> None:
        await self._run("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
