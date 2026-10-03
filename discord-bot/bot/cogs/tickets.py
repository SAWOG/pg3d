from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import FIELD_LIMIT, clip, collect_history, is_staff, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

HISTORY_LIMIT = 500
REQUEST_MESSAGES = 4   # kullanıcının ilk kaç mesajı "talep" sayılsın


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
        user_msgs = [m for m in messages if not is_staff(m.author)]
        if not user_msgs:
            return None

        opener = user_msgs[0].author
        opener_msgs = [m for m in user_msgs if m.author.id == opener.id]
        request_text = "\n".join(m.clean_content for m in opener_msgs[:REQUEST_MESSAGES] if m.clean_content)
        last_user = opener_msgs[-1]
        (request_tr, lang), (last_tr, _) = await self.bot.translator.translate_many(
            [request_text, last_user.clean_content if last_user is not opener_msgs[0] else ""]
        )

        staff_msgs = [m for m in messages if is_staff(m.author)]
        last = messages[-1]
        if not staff_msgs:
            status, color = "🔴 Henüz yetkili yanıtı yok", discord.Color.red()
        elif is_staff(last.author):
            status, color = "🟡 Kullanıcı yanıtı bekleniyor", discord.Color.gold()
        else:
            status, color = "🟠 Yetkili yanıtı bekleniyor", discord.Color.orange()

        embed = discord.Embed(
            title=clip(f"🎫 {channel.name}", 256),
            description=clip(f"**Talep:**\n{request_tr or '*(sadece dosya gönderildi)*'}", 4096),
            color=color,
        )
        if last_tr:
            embed.add_field(name="Son kullanıcı mesajı", value=clip(last_tr, FIELD_LIMIT), inline=False)
        embed.add_field(name="Açan", value=f"{opener.mention}")
        embed.add_field(name="Durum", value=status)
        embed.add_field(name="Kanal", value=channel.mention)
        files = [a.filename for m in user_msgs for a in m.attachments]
        if files:
            embed.add_field(name="Ekler", value=clip(", ".join(files), FIELD_LIMIT), inline=False)
        staff_names = sorted({m.author.display_name for m in staff_msgs})
        embed.add_field(
            name="İlgilenen yetkili", value=clip(", ".join(staff_names), FIELD_LIMIT) if staff_names else "—"
        )
        if lang not in {"tr", "?"}:
            embed.add_field(name="Orijinal dil", value=f"`{lang}`")
        embed.set_footer(text=f"{len(messages)} mesaj · açılış")
        embed.timestamp = messages[0].created_at
        return embed

    async def _auto_summary(self, channel: discord.TextChannel) -> None:
        await asyncio.sleep(self.bot.config.ticket_auto_summary_delay)
        if self.bot.get_channel(channel.id) is None:  # ticket bu sürede kapatılmış
            return
        report = await resolve_text_channel(self.bot, self.bot.config.report_channel_id)
        if report is None:
            return
        try:
            embed = await self.summarize(channel)
            if embed is not None:
                await report.send(content="Yeni ticket", embed=embed)
        except discord.HTTPException as e:
            log.warning("Ticket özeti başarısız (%s): %s", channel.name, e)

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
