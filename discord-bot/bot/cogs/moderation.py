from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import ERR_COLOR, OK_COLOR, clip, embed, hierarchy_error, reply, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

_DURATION_RE = re.compile(r"^\s*(\d{1,5})\s*([smhdw])\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_TIMEOUT = timedelta(days=28)


def parse_duration(text: str) -> timedelta | None:
    """'10m', '2h', '1d' gibi süreleri çevirir."""
    m = _DURATION_RE.match(text)
    if not m:
        return None
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()])


class Moderation(commands.Cog):
    """Dyno / Carl / FlaviBot tarzı moderasyon komutları."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    async def _modlog(self, guild: discord.Guild, action: str, target: discord.abc.User, moderator: discord.abc.User, reason: str, extra: str = "") -> None:
        e = embed(f"{action} · {target}", color=ERR_COLOR)
        e.add_field(name="User", value=f"{target.mention} (`{target.id}`)")
        e.add_field(name="Moderator", value=moderator.mention)
        if extra:
            e.add_field(name="Details", value=extra)
        e.add_field(name="Reason", value=clip(reason, 1000) or "—", inline=False)
        await send_log(self.bot, guild, "modlog.channel", e)

    @staticmethod
    async def _dm(user: discord.User | discord.Member, guild: discord.Guild, action: str, reason: str) -> None:
        try:
            await user.send(embed=embed(f"You were {action} from {guild.name}", reason or None, ERR_COLOR))
        except discord.HTTPException:
            pass  # DM kapalı olabilir

    @staticmethod
    def _check_target(interaction: discord.Interaction, target: discord.Member) -> str | None:
        actor = interaction.user
        assert isinstance(actor, discord.Member)
        return hierarchy_error(actor, target)

    @app_commands.command(name="ban", description="Ban a user (works even if they left the server)")
    @app_commands.describe(user="User to ban", reason="Reason", delete_messages="Delete their recent messages")
    @app_commands.choices(delete_messages=[
        app_commands.Choice(name="Don't delete", value=0),
        app_commands.Choice(name="Last hour", value=3600),
        app_commands.Choice(name="Last 24 hours", value=86400),
        app_commands.Choice(name="Last 7 days", value=604800),
    ])
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str = "",
                  delete_messages: app_commands.Choice[int] | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(user.id)
        if member is not None and (err := self._check_target(interaction, member)):
            return await reply(interaction, err, ok=False)
        seconds = delete_messages.value if delete_messages and delete_messages.value in (0, 3600, 86400, 604800) else 0
        if member is not None:
            await self._dm(member, guild, "banned", reason)
        await guild.ban(user, reason=f"{interaction.user}: {reason}"[:512], delete_message_seconds=seconds)
        await reply(interaction, f"🔨 **{user}** was banned.", ephemeral=False)
        await self._modlog(guild, "🔨 Ban", user, interaction.user, reason)

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="The user's ID", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "") -> None:
        guild = interaction.guild
        assert guild is not None
        if not user_id.strip().isdigit():
            return await reply(interaction, "That's not a valid user ID.", ok=False)
        target = discord.Object(id=int(user_id))
        try:
            await guild.unban(target, reason=f"{interaction.user}: {reason}"[:512])
        except discord.NotFound:
            return await reply(interaction, "That user isn't banned.", ok=False)
        user = await self.bot.fetch_user(target.id)
        await reply(interaction, f"✅ **{user}** was unbanned.", ephemeral=False)
        await self._modlog(guild, "✅ Unban", user, interaction.user, reason)

    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "") -> None:
        assert interaction.guild is not None
        if err := self._check_target(interaction, member):
            return await reply(interaction, err, ok=False)
        await self._dm(member, interaction.guild, "kicked", reason)
        await member.kick(reason=f"{interaction.user}: {reason}"[:512])
        await reply(interaction, f"👢 **{member}** was kicked.", ephemeral=False)
        await self._modlog(interaction.guild, "👢 Kick", member, interaction.user, reason)

    @app_commands.command(name="timeout", description="Timeout a member (e.g. 10m, 2h, 1d — max 28d)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "") -> None:
        assert interaction.guild is not None
        if err := self._check_target(interaction, member):
            return await reply(interaction, err, ok=False)
        delta = parse_duration(duration)
        if delta is None or delta.total_seconds() < 1 or delta > MAX_TIMEOUT:
            return await reply(interaction, "Invalid duration. Use e.g. `10m`, `2h`, `1d` (max 28d).", ok=False)
        await member.timeout(delta, reason=f"{interaction.user}: {reason}"[:512])
        await reply(interaction, f"🔇 **{member}** timed out for {duration}.", ephemeral=False)
        await self._modlog(interaction.guild, "🔇 Timeout", member, interaction.user, reason, duration)

    @app_commands.command(name="untimeout", description="Remove a member's timeout")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        if err := self._check_target(interaction, member):
            return await reply(interaction, err, ok=False)
        await member.timeout(None)
        await reply(interaction, f"🔊 **{member}**'s timeout was removed.", ephemeral=False)
        await self._modlog(interaction.guild, "🔊 Untimeout", member, interaction.user, "")

    @app_commands.command(name="warn", description="Warn a member (auto-timeout after too many warnings)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        if err := self._check_target(interaction, member):
            return await reply(interaction, err, ok=False)
        result = await self.bot.warns.warn(member, interaction.user, reason)
        extra = f" They were timed out for {result.timed_out_minutes} min." if result.timed_out_minutes else ""
        await reply(interaction, f"⚠️ {member.mention} was warned (**{result.count}** active).{extra}", ephemeral=False)
        try:
            await member.send(embed=embed(f"You were warned in {member.guild.name}", reason, ERR_COLOR))
        except discord.HTTPException:
            pass

    @app_commands.command(name="warnings", description="Show a member's active warnings")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = await self.bot.warns.list(member.guild.id, member.id)
        if not rows:
            return await reply(interaction, f"{member.mention} has no active warnings.")
        lines = [f"`#{wid}` <t:{ts}:R> by <@{mod}> — {clip(reason, 120)}" for wid, mod, reason, ts in rows]
        await interaction.response.send_message(
            embed=embed(f"{member} · {len(rows)} warnings", "\n".join(lines)), ephemeral=True
        )

    @app_commands.command(name="clearwarnings", description="Delete all of a member's warnings")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        n = await self.bot.warns.clear(member.guild.id, member.id)
        await reply(interaction, f"Cleared {n} warnings for {member.mention}.")
        await self._modlog(member.guild, "🧹 Warnings cleared", member, interaction.user, "", str(n))

    @app_commands.command(name="purge", description="Bulk delete messages (max 100, younger than 14 days)")
    @app_commands.describe(amount="How many messages to check", user="Only delete this user's messages")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    @app_commands.guild_only()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100],
                    user: discord.User | None = None) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return await reply(interaction, "This channel type isn't supported.", ok=False)
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await channel.purge(limit=amount, check=lambda m: user is None or m.author.id == user.id)
        await reply(interaction, f"🧹 Deleted {len(deleted)} messages.")
        assert interaction.guild is not None
        e = embed(f"🧹 Purge · #{channel.name}", f"{len(deleted)} messages by {interaction.user.mention}", ERR_COLOR)
        await send_log(self.bot, interaction.guild, "modlog.channel", e)

    @app_commands.command(name="slowmode", description="Set slowmode for this channel (0 = off)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return await reply(interaction, "Only works in text channels.", ok=False)
        await interaction.channel.edit(slowmode_delay=seconds)
        await reply(interaction, f"🐢 Slowmode set to {seconds}s." if seconds else "Slowmode disabled.", ephemeral=False)

    async def _set_lock(self, interaction: discord.Interaction, channel: discord.TextChannel | None, locked: bool) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await reply(interaction, "Only works in text channels.", ok=False)
        overwrite = target.overwrites_for(target.guild.default_role)
        overwrite.update(send_messages=False if locked else None)
        await target.set_permissions(target.guild.default_role, overwrite=overwrite, reason=f"{interaction.user}")
        await reply(interaction, f"🔒 {target.mention} locked." if locked else f"🔓 {target.mention} unlocked.", ephemeral=False)
        e = embed(f"{'🔒 Lock' if locked else '🔓 Unlock'} · #{target.name}", f"by {interaction.user.mention}", ERR_COLOR if locked else OK_COLOR)
        await send_log(self.bot, target.guild, "modlog.channel", e)

    @app_commands.command(name="lock", description="Stop @everyone from sending messages in a channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self._set_lock(interaction, channel, True)

    @app_commands.command(name="unlock", description="Allow @everyone to send messages again")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self._set_lock(interaction, channel, False)
