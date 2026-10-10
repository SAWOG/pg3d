from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import embed, reply, require_manage_guild
from ..warns import KEY_EXPIRE_DAYS, KEY_TIMEOUT_AT, KEY_TIMEOUT_MIN

if TYPE_CHECKING:
    from ..main import HelperBot

# /setup show içinde listelenen kanal ayarları: (anahtar, açıklama)
CHANNEL_KEYS: tuple[tuple[str, str], ...] = (
    ("log.channel", "Olay logları"),
    ("modlog.channel", "Moderasyon logları"),
    ("welcome.channel", "Hoş geldin"),
    ("leave.channel", "Güle güle"),
    ("invites.channel", "Davet logları"),
    ("levels.channel", "Seviye atlama"),
    ("ticket.log_channel", "Ticket logları"),
)


async def _check_sendable(interaction: discord.Interaction, channel: discord.TextChannel) -> bool:
    perms = channel.permissions_for(channel.guild.me)
    if perms.send_messages and perms.embed_links:
        return True
    await reply(interaction, f"Botun {channel.mention} kanalında mesaj/embed gönderme izni yok.", ok=False)
    return False


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Setup(commands.GroupCog, group_name="setup", group_description="Genel bot ayarları"):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage_guild(interaction)

    async def _set_channel(self, interaction: discord.Interaction, key: str, channel: discord.TextChannel | None, label: str) -> None:
        assert interaction.guild is not None
        if channel is None:
            await self.bot.settings.delete(interaction.guild.id, key)
            return await reply(interaction, f"{label} kapatıldı.")
        if await _check_sendable(interaction, channel):
            await self.bot.settings.set(interaction.guild.id, key, channel.id)
            await reply(interaction, f"{label}: {channel.mention}")

    @app_commands.command(name="logs", description="Olay log kanalı (silinen/düzenlenen mesaj, giriş/çıkış...). Boş = kapat")
    async def logs(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self._set_channel(interaction, "log.channel", channel, "Olay logları")

    @app_commands.command(name="modlog", description="Moderasyon log kanalı (ban, kick, uyarı, automod). Boş = kapat")
    async def modlog(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self._set_channel(interaction, "modlog.channel", channel, "Moderasyon logları")

    @app_commands.command(name="warns", description="Kaç uyarıda kaç dakika otomatik timeout; uyarılar kaç gün geçerli")
    @app_commands.describe(timeout_at="Kaç uyarıda timeout (0 = kapalı)", minutes="Timeout süresi (dk)", expire_days="Uyarı kaç gün geçerli")
    async def warns(self, interaction: discord.Interaction, timeout_at: app_commands.Range[int, 0, 50],
                    minutes: app_commands.Range[int, 1, 40320] = 30, expire_days: app_commands.Range[int, 1, 3650] = 30) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        await self.bot.settings.set(gid, KEY_TIMEOUT_AT, timeout_at)
        await self.bot.settings.set(gid, KEY_TIMEOUT_MIN, minutes)
        await self.bot.settings.set(gid, KEY_EXPIRE_DAYS, expire_days)
        text = f"{timeout_at} uyarıda {minutes} dk timeout" if timeout_at else "Otomatik timeout kapalı"
        await reply(interaction, f"{text}; uyarılar {expire_days} gün geçerli.")

    @app_commands.command(name="show", description="Bütün ayarlı kanalları göster")
    async def show(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        s = self.bot.settings
        lines = [f"**{label}:** {f'<#{cid}>' if (cid := s.get_int(gid, key)) else '—'}" for key, label in CHANNEL_KEYS]
        lines.append(
            f"**Uyarı → timeout:** {s.get_int(gid, KEY_TIMEOUT_AT, 3)} uyarı / {s.get_int(gid, KEY_TIMEOUT_MIN, 30)} dk"
        )
        lines.append(f"**Automod:** {'açık' if s.get_bool(gid, 'automod.enabled') else 'kapalı'} (`/automod status`)")
        await interaction.response.send_message(embed=embed("⚙️ Ayarlar", "\n".join(lines)), ephemeral=True)
