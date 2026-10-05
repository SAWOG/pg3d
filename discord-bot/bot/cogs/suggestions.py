from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..suggestions import SortOrder, collect_pending
from ..ui.review_panel import ReviewPanel
from ..util import staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

_SORTS: dict[str, SortOrder] = {"votes": "votes", "newest": "newest", "oldest": "oldest"}


class Suggestions(commands.Cog):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    @app_commands.command(name="summary", description="Cevaplanmamış önerileri Türkçe özetler; kabul/red paneli açar")
    @app_commands.describe(
        kanal="Öneri kanalı (boşsa .env'deki SUGGESTION_CHANNEL_ID)",
        min_oy="En az kaç oy almış öneriler gösterilsin",
        siralama="Sıralama",
    )
    @app_commands.choices(
        siralama=[
            app_commands.Choice(name="En çok oy", value="votes"),
            app_commands.Choice(name="En yeni", value="newest"),
            app_commands.Choice(name="En eski", value="oldest"),
        ]
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @staff_only()
    async def summary(
        self,
        interaction: discord.Interaction,
        kanal: discord.TextChannel | None = None,
        min_oy: app_commands.Range[int, 0, 1000] = 0,
        siralama: app_commands.Choice[str] | None = None,
    ) -> None:
        cfg = self.bot.config
        channel = kanal
        if channel is None and cfg.suggestion_channel_id:
            found = interaction.guild.get_channel(cfg.suggestion_channel_id) if interaction.guild else None
            channel = found if isinstance(found, discord.TextChannel) else None
        if channel is None:
            await interaction.response.send_message("Bir kanal seç ya da .env'de SUGGESTION_CHANNEL_ID ayarla.", ephemeral=True)
            return

        member = interaction.user
        assert isinstance(member, discord.Member)
        bot_perms = channel.permissions_for(channel.guild.me)
        if not channel.permissions_for(member).read_message_history:
            await interaction.response.send_message("Bu kanalı görme yetkin yok.", ephemeral=True)
            return
        if not (bot_perms.read_message_history and bot_perms.send_messages and bot_perms.embed_links):
            await interaction.response.send_message(
                f"Botun {channel.mention} kanalında *Read Message History, Send Messages, Embed Links* izinleri olmalı.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        sort = _SORTS.get(siralama.value if siralama else "", "votes")
        items = await collect_pending(channel, self.bot.store, cfg, min_votes=min_oy, sort=sort)

        panel = ReviewPanel(self.bot, member.id, channel, items, min_votes=min_oy, sort=sort)
        panel.origin = interaction
        embed = await panel.render()
        await interaction.followup.send(embed=embed, view=panel, ephemeral=True)
