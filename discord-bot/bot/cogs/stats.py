from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..util import manage_guild_only, reply

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

KEY = "stats.channels"
COUNTERS: dict[str, str] = {
    "members": "👥 Members: {n}",
    "humans": "🙂 Humans: {n}",
    "bots": "🤖 Bots: {n}",
    "boosts": "🚀 Boosts: {n}",
}


def counts(guild: discord.Guild) -> dict[str, int]:
    total = guild.member_count or len(guild.members)
    bots = sum(1 for m in guild.members if m.bot)
    return {"members": total, "humans": total - bots, "bots": bots, "boosts": guild.premium_subscription_count}


class Stats(commands.Cog):
    """Server Stat: üye/bot/boost sayısını gösteren kilitli ses kanalları (10 dakikada bir güncellenir)."""

    stats = app_commands.Group(
        name="stats", description="Sunucu istatistik kanalları", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.update_loop.start()

    async def cog_unload(self) -> None:
        self.update_loop.cancel()

    def _config(self, guild_id: int) -> dict[str, int]:
        value = self.bot.settings.get(guild_id, KEY, {})
        return {str(k): int(v) for k, v in value.items()} if isinstance(value, dict) else {}

    async def refresh(self, guild: discord.Guild) -> None:
        values = counts(guild)
        for key, channel_id in self._config(guild.id).items():
            channel = guild.get_channel(channel_id)
            template = COUNTERS.get(key)
            if not isinstance(channel, discord.VoiceChannel) or template is None:
                continue
            name = template.format(n=f"{values[key]:,}")
            if channel.name != name:  # sadece değiştiyse: Discord ad değişikliğini 10 dk'da 2 ile sınırlar
                try:
                    await channel.edit(name=name, reason="Server stats")
                except discord.HTTPException as e:
                    log.warning("İstatistik kanalı güncellenemedi: %s", e)

    # Ad değişikliği limiti yüzünden 10 dakikadan sık güncellemek işe yaramaz
    @tasks.loop(minutes=10)
    async def update_loop(self) -> None:
        for guild in self.bot.guilds:
            if self._config(guild.id):
                await self.refresh(guild)

    @update_loop.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    @stats.command(name="setup", description="İstatistik kanallarını oluştur")
    @manage_guild_only()
    async def setup(self, interaction: discord.Interaction, members: bool = True, humans: bool = False,
                    bots: bool = True, boosts: bool = False) -> None:
        guild = interaction.guild
        assert guild is not None
        if not guild.me.guild_permissions.manage_channels:
            return await reply(interaction, "Botun **Kanalları Yönet** izni olmalı.", ok=False)
        wanted = [k for k, on in (("members", members), ("humans", humans), ("bots", bots), ("boosts", boosts)) if on]
        if not wanted:
            return await reply(interaction, "En az bir sayaç seç.", ok=False)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._remove_channels(guild)
        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, view_channel=True),
        }
        category = await guild.create_category("📊 Server Stats", overwrites=overwrites, position=0)
        values = counts(guild)
        config: dict[str, int] = {"category": category.id}
        for key in wanted:
            ch = await guild.create_voice_channel(COUNTERS[key].format(n=f"{values[key]:,}"), category=category)
            config[key] = ch.id
        await self.bot.settings.set(guild.id, KEY, config)
        await reply(interaction, "İstatistik kanalları oluşturuldu; 10 dakikada bir güncellenecek.")

    async def _remove_channels(self, guild: discord.Guild) -> None:
        for channel_id in self._config(guild.id).values():
            channel = guild.get_channel(channel_id)
            if channel is not None:
                try:
                    await channel.delete(reason="Server stats removed")
                except discord.HTTPException:
                    pass
        await self.bot.settings.delete(guild.id, KEY)

    @stats.command(name="remove", description="İstatistik kanallarını sil")
    @manage_guild_only()
    async def remove(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._remove_channels(interaction.guild)
        await reply(interaction, "Silindi.")
