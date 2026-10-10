from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import OK_COLOR, embed, reply, require_manage_guild, role_assignable

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

DEFAULT_WELCOME = "Welcome {user} to **{server}**! You are member #{count}."
DEFAULT_LEAVE = "**{name}** left the server."
PLACEHOLDER_HELP = "Değişkenler: {user} (etiket), {name} (isim), {server}, {count} (üye sayısı)"


def render(template: str, member: discord.Member) -> str:
    # str.format yerine replace: kullanıcı şablonundaki {x.__class__} gibi ifadeler çalıştırılmaz
    return (
        template.replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count or 0))
    )[:2000]


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Welcome(commands.GroupCog, group_name="welcome", group_description="Hoş geldin / güle güle mesajları ve otomatik rol"):
    autorole = app_commands.Group(name="autorole", description="Yeni üyelere otomatik verilecek roller")

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage_guild(interaction)

    async def _post(self, member: discord.Member, channel_key: str, msg_key: str, default: str) -> None:
        s = self.bot.settings
        channel = member.guild.get_channel(s.get_int(member.guild.id, channel_key))
        if not isinstance(channel, discord.TextChannel):
            return
        text = render(s.get_str(member.guild.id, msg_key, default), member)
        e = embed(description=text, color=OK_COLOR)
        e.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(
                content=member.mention if channel_key == "welcome.channel" else None,
                embed=e,
                allowed_mentions=discord.AllowedMentions(users=[member], everyone=False, roles=False),
            )
        except discord.HTTPException as e2:
            log.warning("Hoş geldin mesajı gönderilemedi: %s", e2)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        roles = [r for rid in self.bot.settings.get_ids(member.guild.id, "autorole.roles")
                 if (r := member.guild.get_role(rid)) is not None and role_assignable(r) is None]
        if roles and not member.bot:
            try:
                await member.add_roles(*roles, reason="Autorole")
            except discord.HTTPException as e:
                log.warning("Otomatik rol verilemedi: %s", e)
        await self._post(member, "welcome.channel", "welcome.message", DEFAULT_WELCOME)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._post(member, "leave.channel", "leave.message", DEFAULT_LEAVE)

    @app_commands.command(name="set", description="Hoş geldin kanalı ve mesajı. " + "{user} {name} {server} {count}")
    @app_commands.describe(channel="Kanal", message=PLACEHOLDER_HELP)
    async def set_welcome(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str | None = None) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, "welcome.channel", channel.id)
        if message:
            await self.bot.settings.set(interaction.guild.id, "welcome.message", message[:1500])
        await reply(interaction, f"Hoş geldin mesajları {channel.mention} kanalına gidecek. `/welcome test` ile dene.")

    @app_commands.command(name="leave", description="Güle güle kanalı ve mesajı")
    @app_commands.describe(channel="Kanal", message=PLACEHOLDER_HELP)
    async def set_leave(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str | None = None) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, "leave.channel", channel.id)
        if message:
            await self.bot.settings.set(interaction.guild.id, "leave.message", message[:1500])
        await reply(interaction, f"Güle güle mesajları {channel.mention} kanalına gidecek.")

    @app_commands.command(name="off", description="Hoş geldin ve güle güle mesajlarını kapat")
    async def off(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        for key in ("welcome.channel", "leave.channel"):
            await self.bot.settings.delete(interaction.guild.id, key)
        await reply(interaction, "Kapatıldı.")

    @app_commands.command(name="test", description="Hoş geldin mesajını kendinle dene")
    async def test(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.user, discord.Member)
        await self._post(interaction.user, "welcome.channel", "welcome.message", DEFAULT_WELCOME)
        await reply(interaction, "Gönderildi (kanal ayarlıysa).")

    @autorole.command(name="add", description="Yeni üyelere verilecek rol ekle")
    async def autorole_add(self, interaction: discord.Interaction, role: discord.Role) -> None:
        assert interaction.guild is not None
        if err := role_assignable(role):
            return await reply(interaction, err, ok=False)
        ok = await self.bot.settings.add_to_list(interaction.guild.id, "autorole.roles", role.id, limit=10)
        await reply(interaction, f"{role.mention} yeni üyelere verilecek." if ok else "Zaten ekli veya 10 rol sınırı dolu.", ok=ok)

    @autorole.command(name="remove", description="Otomatik rolü kaldır")
    async def autorole_remove(self, interaction: discord.Interaction, role: discord.Role) -> None:
        assert interaction.guild is not None
        ok = await self.bot.settings.remove_from_list(interaction.guild.id, "autorole.roles", role.id)
        await reply(interaction, "Kaldırıldı." if ok else "Bu rol listede yok.", ok=ok)
