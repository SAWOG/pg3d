from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ..util import ERR_COLOR, INFO_COLOR, OK_COLOR, clip, embed, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

KEY = "log.channel"
WARN_COLOR = discord.Color.orange()


class ServerLogs(commands.Cog):
    """Carl / Dyno tarzı olay logları: silinen/düzenlenen mesaj, giriş/çıkış, ban, rol, ses."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    def _enabled(self, guild: discord.Guild | None) -> bool:
        return guild is not None and bool(self.bot.settings.get_int(guild.id, KEY))

    async def _send(self, guild: discord.Guild, e: discord.Embed) -> None:
        e.timestamp = datetime.now(timezone.utc)
        await send_log(self.bot, guild, KEY, e)

    def _skip_message(self, message: discord.Message) -> bool:
        return (
            message.guild is None
            or message.author.bot
            or not self._enabled(message.guild)
            or message.channel.id == self.bot.settings.get_int(message.guild.id, KEY)
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if self._skip_message(message):
            return
        assert message.guild is not None
        e = embed(f"🗑️ Message deleted in #{getattr(message.channel, 'name', '?')}", clip(message.content, 3500) or "*(no text)*", ERR_COLOR)
        e.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        if message.attachments:
            e.add_field(name="Attachments", value=clip(", ".join(a.filename for a in message.attachments), 1000))
        e.set_footer(text=f"User ID {message.author.id}")
        await self._send(message.guild, e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None or not self._enabled(messages[0].guild):
            return
        ch = getattr(messages[0].channel, "name", "?")
        await self._send(messages[0].guild, embed(f"🗑️ {len(messages)} messages bulk-deleted in #{ch}", color=ERR_COLOR))

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if self._skip_message(after) or before.content == after.content:
            return
        assert after.guild is not None
        e = embed(f"✏️ Message edited in #{getattr(after.channel, 'name', '?')}", f"[Jump]({after.jump_url})", WARN_COLOR)
        e.set_author(name=str(after.author), icon_url=after.author.display_avatar.url)
        e.add_field(name="Before", value=clip(before.content, 1000) or "—", inline=False)
        e.add_field(name="After", value=clip(after.content, 1000) or "—", inline=False)
        await self._send(after.guild, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self._enabled(member.guild):
            return
        age_days = (datetime.now(timezone.utc) - member.created_at).days
        e = embed("📥 Member joined", f"{member.mention} · {member}", OK_COLOR)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Account created", value=f"<t:{int(member.created_at.timestamp())}:R>" + (" ⚠️ new account" if age_days < 7 else ""))
        e.add_field(name="Member #", value=str(member.guild.member_count))
        await self._send(member.guild, e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not self._enabled(member.guild):
            return
        roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
        e = embed("📤 Member left", f"{member.mention} · {member}", ERR_COLOR)
        e.add_field(name="Roles", value=clip(" ".join(roles), 1000) or "—", inline=False)
        if member.joined_at:
            e.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>")
        await self._send(member.guild, e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        if self._enabled(guild):
            await self._send(guild, embed("🔨 Member banned", f"{user.mention} · {user}", ERR_COLOR))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        if self._enabled(guild):
            await self._send(guild, embed("✅ Member unbanned", f"{user.mention} · {user}", OK_COLOR))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if not self._enabled(after.guild):
            return
        if before.nick != after.nick:
            e = embed("📝 Nickname changed", after.mention, INFO_COLOR)
            e.add_field(name="Before", value=before.nick or "—")
            e.add_field(name="After", value=after.nick or "—")
            await self._send(after.guild, e)
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        if added or removed:
            e = embed("🎭 Roles updated", after.mention, INFO_COLOR)
            if added:
                e.add_field(name="Added", value=clip(" ".join(added), 1000))
            if removed:
                e.add_field(name="Removed", value=clip(" ".join(removed), 1000))
            await self._send(after.guild, e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot or not self._enabled(member.guild) or before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            text, color = f"🔊 {member.mention} joined **{after.channel.name}**", OK_COLOR
        elif after.channel is None and before.channel is not None:
            text, color = f"🔇 {member.mention} left **{before.channel.name}**", ERR_COLOR
        else:
            assert before.channel is not None and after.channel is not None
            text, color = f"🔀 {member.mention} moved **{before.channel.name}** → **{after.channel.name}**", INFO_COLOR
        await self._send(member.guild, embed(description=text, color=color))
