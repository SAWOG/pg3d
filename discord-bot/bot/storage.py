from __future__ import annotations

import time
from typing import Literal

from .db import Database

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
    """Hangi önerinin cevaplandığını tutar."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def init(self) -> None:
        await self._db.script(_SCHEMA)

    async def decided_ids(self, channel_id: int) -> set[int]:
        rows = await self._db.fetchall("SELECT message_id FROM decisions WHERE channel_id = ?", (channel_id,))
        return {int(r[0]) for r in rows}

    async def claim(
        self, guild_id: int, channel_id: int, message_id: int, status: Status, reason: str, moderator_id: int
    ) -> bool:
        """Öneriyi atomik olarak karara bağlar. Başka yetkili önce davrandıysa False döner."""
        inserted = await self._db.execute(
            "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, guild_id, channel_id, status, reason, moderator_id, int(time.time())),
        )
        return inserted == 1

    async def release(self, message_id: int) -> None:
        """Kanala cevap gönderilemezse kararı geri alır."""
        await self._db.execute("DELETE FROM decisions WHERE message_id = ?", (message_id,))
