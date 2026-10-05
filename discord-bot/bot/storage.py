from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal

Status = Literal["accepted", "rejected", "dismissed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    message_id   INTEGER PRIMARY KEY,
    guild_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('accepted', 'rejected', 'dismissed')),
    reason       TEXT    NOT NULL,
    moderator_id INTEGER NOT NULL,
    decided_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_channel ON decisions (channel_id);
"""


class DecisionStore:
    """Hangi önerinin cevaplandığını tutar; bloklayan sqlite çağrıları thread'e alınır."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    async def _run(self, sql: str, params: tuple[object, ...]) -> tuple[list[tuple[Any, ...]], int]:
        def work() -> tuple[list[tuple[Any, ...]], int]:
            with self._conn:
                cur = self._conn.execute(sql, params)
                return cur.fetchall(), cur.rowcount

        async with self._lock:
            return await asyncio.to_thread(work)

    async def decided_ids(self, channel_id: int) -> set[int]:
        rows, _ = await self._run("SELECT message_id FROM decisions WHERE channel_id = ?", (channel_id,))
        return {int(r[0]) for r in rows}

    async def claim(
        self, guild_id: int, channel_id: int, message_id: int, status: Status, reason: str, moderator_id: int
    ) -> bool:
        """Öneriyi atomik olarak karara bağlar. Başka yetkili önce davrandıysa False döner."""
        _, inserted = await self._run(
            "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, guild_id, channel_id, status, reason, moderator_id, int(time.time())),
        )
        return inserted == 1

    async def release(self, message_id: int) -> None:
        """Kanala cevap gönderilemezse kararı geri alır."""
        await self._run("DELETE FROM decisions WHERE message_id = ?", (message_id,))
