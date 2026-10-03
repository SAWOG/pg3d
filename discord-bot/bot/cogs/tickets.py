from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..ai import AIError, TicketSummary
from ..util import FIELD_LIMIT, clip, collect_history, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

HISTORY_LIMIT = 500
STATUS_COLORS: dict[str, discord.Color] = {
    "açık": discord.Color.orange(),
    "yanıt bekliyor": discord.Color.gold(),
    "çözüldü": discord.Color.green(),
    "belirsiz": discord.Color.light_grey(),
}


def build_embed(channel: discord.TextChannel, summary: TicketSummary, message_count: int) -> discord.Embed:
    embed = discord.Embed(
        title=clip(f"🎫 {summary.subject}", 256),
        description=clip(summary.request, 4096),
        color=STATUS_COLORS.get(summary.status, discord.Color.light_grey()),
    )
    embed.add_field(name="Kanal", value=channel.mention)
    embed.add_field(name="Durum", value=summary.status)
    embed.add_field(name="Dil", value=clip(summary.original_language, 64))
    if summary.key_details:
        embed.add_field(
            name="Detaylar",
            value=clip("\n".join(f"• {d}" for d in summary.key_details), FIELD_LIMIT),
            inline=False,
        )
    embed.add_field(name="Önerilen adım", value=clip(summary.suggested_action, FIELD_LIMIT), inline=False)
    embed.set_footer(text=f"{message_count} mesaj analiz edildi")
    return embed


class Tickets(commands.Cog):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._pending: set[asyncio.Task[None]] = set()

    async def cog_unload(self) -> None:
        for task in self._pending:
            task.cancel()
        self._pending.clear()

    def is_ticket(self, channel: object) -> bool:
        if not isinstance(channel, discord.TextChannel):
            return False
        cfg = self.bot.config
        if channel.category_id is not None and channel.category_id in cfg.ticket_category_ids:
            return True
        return bool(cfg.ticket_prefix) and channel.name.lower().startswith(cfg.ticket_prefix)

    async def summarize(self, channel: discord.TextChannel) -> discord.Embed | None:
        messages = await collect_history(channel, limit=HISTORY_LIMIT)
        if not messages:
            return None
        summary = await self.bot.ai.summarize_ticket(channel.name, messages)
        return build_embed(channel, summary, len(messages))

    async def _auto_summary(self, channel: discord.TextChannel) -> None:
        await asyncio.sleep(self.bot.config.ticket_auto_summary_delay)
        if self.bot.get_channel(channel.id) is None:  # ticket bu sürede kapatılmış
            return
        report = await resolve_text_channel(self.bot, self.bot.config.report_channel_id)
        if report is None:
            return
        try:
            embed = await self.summarize(channel)
        except AIError as e:
            log.warning("Ticket özeti başarısız (%s): %s", channel.name, e)
            return
        except discord.HTTPException as e:
            log.warning("Ticket geçmişi okunamadı (%s): %s", channel.name, e)
            return
        if embed is not None:
            await report.send(content="Yeni ticket özeti", embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if self.bot.config.ticket_auto_summary_delay <= 0 or not self.is_ticket(channel):
            return
        assert isinstance(channel, discord.TextChannel)
        task = asyncio.create_task(self._auto_summary(channel))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    @app_commands.command(name="ticket-ozet", description="Ticket konuşmasını Türkçe özetler")
    @app_commands.describe(kanal="Özetlenecek ticket kanalı (boşsa bu kanal)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @staff_only()
    async def ticket_summary(
        self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None
    ) -> None:
        channel = kanal or interaction.channel
        if not self.is_ticket(channel):
            await interaction.response.send_message("Bu bir ticket kanalı değil.", ephemeral=True)
            return
        assert isinstance(channel, discord.TextChannel)
        member = interaction.user
        if not isinstance(member, discord.Member) or not channel.permissions_for(member).read_message_history:
            await interaction.response.send_message("Bu kanalı görme yetkin yok.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = await self.summarize(channel)
        if embed is None:
            await interaction.followup.send("Ticket'ta henüz kullanıcı mesajı yok.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)
