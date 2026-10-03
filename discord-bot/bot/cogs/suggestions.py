from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..ai import AIError, SuggestionDigest
from ..util import chunk_lines, collect_history, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

COLOR = discord.Color.blurple()


def build_embeds(digest: SuggestionDigest, hours: int, message_count: int) -> list[discord.Embed]:
    blocks = [f"**Genel bakış:** {digest.overview}"]
    for i, item in enumerate(digest.items, 1):
        by = ", ".join(item.requested_by[:8]) + ("…" if len(item.requested_by) > 8 else "")
        blocks.append(f"**{i}. {item.title}** · 👍 {item.popularity}\n{item.details}\n*Öneren: {by}*")

    embeds: list[discord.Embed] = []
    for idx, chunk in enumerate(chunk_lines(blocks)):
        title = f"Öneri Özeti · son {hours} saat ({message_count} mesaj)" if idx == 0 else None
        embeds.append(discord.Embed(title=title, description=chunk, color=COLOR))
    return embeds


class Suggestions(commands.Cog):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self.daily_digest.change_interval(time=bot.config.daily_summary_time)

    async def cog_load(self) -> None:
        if self.bot.config.suggestion_channel_id:
            self.daily_digest.start()

    async def cog_unload(self) -> None:
        self.daily_digest.cancel()

    async def _digest(self, hours: int) -> list[discord.Embed]:
        channel = await resolve_text_channel(self.bot, self.bot.config.suggestion_channel_id)
        if channel is None:
            raise AIError("SUGGESTION_CHANNEL_ID geçersiz veya bot kanalı göremiyor")
        after = discord.Object(id=discord.utils.time_snowflake(datetime.now(timezone.utc) - timedelta(hours=hours)))
        messages = await collect_history(channel, limit=None, after=after)
        if not messages:
            return [discord.Embed(description=f"Son {hours} saatte öneri yok.", color=COLOR)]
        digest = await self.bot.ai.summarize_suggestions(messages)
        return build_embeds(digest, hours, len(messages))

    @tasks.loop(hours=24)  # gerçek saat __init__ içinde DAILY_SUMMARY_TIME ile ayarlanır
    async def daily_digest(self) -> None:
        report = await resolve_text_channel(self.bot, self.bot.config.report_channel_id)
        if report is None:
            log.warning("REPORT_CHANNEL_ID bulunamadı, günlük özet atlanıyor")
            return
        try:
            embeds = await self._digest(24)
        except AIError as e:
            await report.send(f"⚠️ Günlük öneri özeti oluşturulamadı: {e}")
            return
        for embed in embeds:
            await report.send(embed=embed)

    @daily_digest.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="oneri-ozet", description="Öneri kanalını Türkçe özetler")
    @app_commands.describe(saat="Kaç saat geriye bakılsın (1-168)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @staff_only()
    async def suggestion_summary(
        self, interaction: discord.Interaction, saat: app_commands.Range[int, 1, 168] = 24
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        for embed in await self._digest(saat):
            await interaction.followup.send(embed=embed, ephemeral=True)
