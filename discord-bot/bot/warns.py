from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import discord

from .util import ERR_COLOR, clip, embed, send_log

if TYPE_CHECKING:
    from .main import HelperBot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason       TEXT    NOT NULL,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings (guild_id, user_id, created_at);
"""

# Ayar anahtarları (/setup warns ile değiştirilir)
KEY_TIMEOUT_AT = "warn.timeout_at"
KEY_TIMEOUT_MIN = "warn.timeout_minutes"
KEY_EXPIRE_DAYS = "warn.expire_days"


@dataclass(frozen=True, slots=True)
class WarnResult:
    count: int
    timed_out_minutes: int


class WarningService:
    """/warn ve automod'un ortak kullandığı uyarı + otomatik timeout mantığı."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    async def init(self) -> None:
        await self.bot.db.script(_SCHEMA)

    def _cutoff(self, guild_id: int) -> int:
        days = self.bot.settings.get_int(guild_id, KEY_EXPIRE_DAYS, 30)
        return int(time.time()) - days * 86400

    async def warn(self, member: discord.Member, moderator: discord.abc.User, reason: str) -> WarnResult:
        guild = member.guild
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild.id, member.id, moderator.id, clip(reason, 500), int(time.time())),
        )
        count = await self.count(guild.id, member.id)
        threshold = self.bot.settings.get_int(guild.id, KEY_TIMEOUT_AT, 3)
        minutes = 0
        if threshold and count >= threshold and not member.is_timed_out():
            minutes = self.bot.settings.get_int(guild.id, KEY_TIMEOUT_MIN, 30)
            try:
                await member.timeout(timedelta(minutes=minutes), reason=f"{count} warnings")
            except discord.HTTPException:
                minutes = 0

        e = embed(f"⚠️ Warn · {member}", color=ERR_COLOR)
        e.add_field(name="User", value=f"{member.mention} (`{member.id}`)")
        e.add_field(name="Moderator", value=moderator.mention)
        e.add_field(name="Count", value=str(count))
        e.add_field(name="Reason", value=clip(reason, 1000) or "—", inline=False)
        if minutes:
            e.add_field(name="Auto timeout", value=f"{minutes} min", inline=False)
        await send_log(self.bot, guild, "modlog.channel", e)
        return WarnResult(count, minutes)

    async def count(self, guild_id: int, user_id: int) -> int:
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
            (guild_id, user_id, self._cutoff(guild_id)),
        )
        return int(row[0]) if row else 0

    async def list(self, guild_id: int, user_id: int, limit: int = 15) -> list[tuple[int, int, str, int]]:
        """(id, moderator_id, reason, created_at)"""
        rows = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? "
            "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, user_id, self._cutoff(guild_id), limit),
        )
        return [(int(r[0]), int(r[1]), str(r[2]), int(r[3])) for r in rows]

    async def clear(self, guild_id: int, user_id: int) -> int:
        return await self.bot.db.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
