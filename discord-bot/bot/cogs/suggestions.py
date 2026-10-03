from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..filters import normalize
from ..util import chunk_lines, clip, collect_history, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

COLOR = discord.Color.blurple()
UP = frozenset({"👍", "✅", "⬆️", "🔼", "❤️"})
DOWN = frozenset({"👎", "❌", "⬇️", "🔽"})
SIMILARITY = 0.72   # bu orandan benzer öneriler tek maddede birleşir
MAX_ITEMS = 30


class DigestError(RuntimeError):
    pass


@dataclass(slots=True)
class Suggestion:
    text: str
    source_lang: str
    url: str
    score: int
    authors: list[str] = field(default_factory=list)
    norm: str = ""
    merged: int = 1


def reaction_score(message: discord.Message) -> int:
    up = down = other = 0
    for r in message.reactions:
        emoji = str(r.emoji)
        n = r.count - (1 if r.me else 0)
        if emoji in UP:
            up += n
        elif emoji in DOWN:
            down += n
        else:
            other += n
    return up - down if up or down else other


def group_similar(items: list[Suggestion]) -> list[Suggestion]:
    """Benzer metinleri birleştirir: O(n²) ama günlük öneri sayısı için yeterli."""
    groups: list[Suggestion] = []
    for item in items:
        for g in groups:
            if item.norm and SequenceMatcher(None, g.norm, item.norm).ratio() >= SIMILARITY:
                g.score += item.score + 1  # aynı şeyi isteyen ek kişi = +1 destek
                g.merged += 1
                if item.authors[0] not in g.authors:
                    g.authors.append(item.authors[0])
                break
        else:
            groups.append(item)
    groups.sort(key=lambda s: s.score, reverse=True)
    return groups


def build_embeds(items: list[Suggestion], hours: int, message_count: int) -> list[discord.Embed]:
    blocks: list[str] = []
    for i, s in enumerate(items[:MAX_ITEMS], 1):
        lang = f" · `{s.source_lang}`" if s.source_lang not in {"tr", "?"} else ""
        extra = f" · {s.merged} benzer mesaj" if s.merged > 1 else ""
        by = ", ".join(s.authors[:6]) + ("…" if len(s.authors) > 6 else "")
        blocks.append(f"**{i}.** {clip(s.text, 600)}\n👍 {s.score}{extra}{lang} · *{by}* · [mesaj]({s.url})")
    if len(items) > MAX_ITEMS:
        blocks.append(f"*…ve {len(items) - MAX_ITEMS} öneri daha*")

    embeds: list[discord.Embed] = []
    for idx, chunk in enumerate(chunk_lines(blocks)):
        title = f"Öneri Özeti · son {hours} saat ({message_count} mesaj, {len(items)} öneri)" if idx == 0 else None
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
            raise DigestError("SUGGESTION_CHANNEL_ID geçersiz veya bot kanalı göremiyor")
        after = discord.Object(id=discord.utils.time_snowflake(datetime.now(timezone.utc) - timedelta(hours=hours)))
        messages = [m for m in await collect_history(channel, after=after) if m.clean_content.strip()]
        if not messages:
            return [discord.Embed(description=f"Son {hours} saatte öneri yok.", color=COLOR)]

        translations = await self.bot.translator.translate_many([m.clean_content for m in messages])
        items = [
            Suggestion(
                text=text,
                source_lang=lang,
                url=m.jump_url,
                score=reaction_score(m),
                authors=[m.author.display_name],
                norm=normalize(text),
            )
            for m, (text, lang) in zip(messages, translations)
        ]
        return build_embeds(group_similar(items), hours, len(messages))

    @tasks.loop(hours=24)  # gerçek saat __init__ içinde DAILY_SUMMARY_TIME ile ayarlanır
    async def daily_digest(self) -> None:
        report = await resolve_text_channel(self.bot, self.bot.config.report_channel_id)
        if report is None:
            log.warning("REPORT_CHANNEL_ID bulunamadı, günlük özet atlanıyor")
            return
        try:
            embeds = await self._digest(24)
        except (DigestError, discord.HTTPException) as e:
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
        try:
            embeds = await self._digest(saat)
        except DigestError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)
