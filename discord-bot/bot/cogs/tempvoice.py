from __future__ import annotations

import logging
import time
from collections import deque
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import clip, manage_guild_only, reply

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

K = "tempvoice."
CREATE_COOLDOWN = 10.0
RENAME_LIMIT, RENAME_WINDOW = 2, 600.0  # Discord: kanal adı 10 dakikada en fazla 2 kez değişebilir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS temp_voice (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL
);
"""


class TempVoice(commands.Cog):
    """VoiceMaster: 'Join to Create' kanalına giren herkese kendi ses odası açılır, boşalınca silinir."""

    voice = app_commands.Group(name="voice", description="Manage your temporary voice channel", guild_only=True)

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._owners: dict[int, int] = {}  # channel_id -> owner_id (DB'nin bellek kopyası)
        self._last_create: dict[int, float] = {}
        self._renames: dict[int, deque[float]] = {}

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        for cid, owner in await self.bot.db.fetchall("SELECT channel_id, owner_id FROM temp_voice"):
            self._owners[int(cid)] = int(owner)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Bot kapalıyken boşalan odaları temizle
        for cid in list(self._owners):
            channel = self.bot.get_channel(cid)
            if not isinstance(channel, discord.VoiceChannel):
                await self._forget(cid)
            elif not channel.members:
                await self._delete(channel)

    async def _forget(self, channel_id: int) -> None:
        self._owners.pop(channel_id, None)
        self._renames.pop(channel_id, None)
        await self.bot.db.execute("DELETE FROM temp_voice WHERE channel_id = ?", (channel_id,))

    async def _delete(self, channel: discord.VoiceChannel) -> None:
        await self._forget(channel.id)
        try:
            await channel.delete(reason="Temp voice empty")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if before.channel == after.channel:
            return
        if isinstance(before.channel, discord.VoiceChannel) and before.channel.id in self._owners and not before.channel.members:
            await self._delete(before.channel)

        hub_id = self.bot.settings.get_int(member.guild.id, K + "hub")
        if member.bot or after.channel is None or after.channel.id != hub_id:
            return
        now = time.monotonic()
        if now - self._last_create.get(member.id, 0.0) < CREATE_COOLDOWN:  # gir-çık spam'i ile kanal yağdırılmasın
            return
        self._last_create[member.id] = now
        hub = after.channel
        overwrites = dict(hub.category.overwrites) if hub.category else {}
        overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True, move_members=True, view_channel=True)
        overwrites[member.guild.me] = discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True, view_channel=True)
        try:
            channel = await member.guild.create_voice_channel(
                clip(f"{member.display_name}'s room", 100), category=hub.category, overwrites=overwrites, reason="Temp voice"
            )
        except discord.HTTPException as e:
            log.warning("Geçici ses kanalı açılamadı: %s", e)
            return
        self._owners[channel.id] = member.id
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO temp_voice (channel_id, guild_id, owner_id) VALUES (?, ?, ?)", (channel.id, member.guild.id, member.id)
        )
        try:
            await member.move_to(channel)
        except discord.HTTPException:
            await self._delete(channel)

    # ---------- Komutlar ----------

    async def _owned_channel(self, interaction: discord.Interaction, *, allow_claim: bool = False) -> discord.VoiceChannel | None:
        member = interaction.user
        channel = member.voice.channel if isinstance(member, discord.Member) and member.voice else None
        if not isinstance(channel, discord.VoiceChannel) or channel.id not in self._owners:
            await reply(interaction, "Join your temporary voice channel first.", ok=False)
            return None
        if not allow_claim and self._owners[channel.id] != member.id:
            await reply(interaction, "Only the channel owner can do this. Use `/voice claim` if they left.", ok=False)
            return None
        return channel

    @voice.command(name="lock", description="Nobody else can join")
    async def lock(self, interaction: discord.Interaction) -> None:
        if ch := await self._owned_channel(interaction):
            await ch.set_permissions(ch.guild.default_role, connect=False)
            await reply(interaction, "🔒 Channel locked.")

    @voice.command(name="unlock", description="Everyone can join again")
    async def unlock(self, interaction: discord.Interaction) -> None:
        if ch := await self._owned_channel(interaction):
            await ch.set_permissions(ch.guild.default_role, connect=None)
            await reply(interaction, "🔓 Channel unlocked.")

    @voice.command(name="limit", description="Set a user limit (0 = no limit)")
    async def limit(self, interaction: discord.Interaction, users: app_commands.Range[int, 0, 99]) -> None:
        if ch := await self._owned_channel(interaction):
            await ch.edit(user_limit=users)
            await reply(interaction, f"👥 User limit: {users or 'none'}.")

    @voice.command(name="name", description="Rename your channel")
    async def name(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 100]) -> None:
        if not (ch := await self._owned_channel(interaction)):
            return
        now = time.monotonic()
        history = self._renames.setdefault(ch.id, deque())
        while history and now - history[0] > RENAME_WINDOW:
            history.popleft()
        if len(history) >= RENAME_LIMIT:
            return await reply(interaction, f"Discord only allows 2 renames per 10 minutes. Try again <t:{int(time.time() + RENAME_WINDOW - (now - history[0]))}:R>.", ok=False)
        history.append(now)
        await ch.edit(name=name)
        await reply(interaction, f"✏️ Renamed to **{name}**.")

    @voice.command(name="permit", description="Let someone join even when locked")
    async def permit(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if ch := await self._owned_channel(interaction):
            await ch.set_permissions(user, connect=True, view_channel=True)
            await reply(interaction, f"✅ {user.mention} can join.")

    @voice.command(name="reject", description="Kick someone out and block them")
    async def reject(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not (ch := await self._owned_channel(interaction)):
            return
        if user.id == interaction.user.id or user.guild_permissions.manage_channels:
            return await reply(interaction, "You can't reject that user.", ok=False)
        await ch.set_permissions(user, connect=False)
        if user.voice and user.voice.channel == ch:
            await user.move_to(None)
        await reply(interaction, f"⛔ {user.mention} was removed.")

    @voice.command(name="claim", description="Become the owner if the owner left")
    async def claim(self, interaction: discord.Interaction) -> None:
        if not (ch := await self._owned_channel(interaction, allow_claim=True)):
            return
        owner_id = self._owners[ch.id]
        if any(m.id == owner_id for m in ch.members):
            return await reply(interaction, "The owner is still here.", ok=False)
        self._owners[ch.id] = interaction.user.id
        await self.bot.db.execute("UPDATE temp_voice SET owner_id = ? WHERE channel_id = ?", (interaction.user.id, ch.id))
        await reply(interaction, "👑 You're now the owner of this channel.")

    @voice.command(name="setup", description="'Join to Create' kanalını oluştur (Yönetici)")
    @app_commands.describe(category="Odaların açılacağı kategori (boşsa yeni oluşturulur)")
    @manage_guild_only()
    async def setup(self, interaction: discord.Interaction, category: discord.CategoryChannel | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if not guild.me.guild_permissions.manage_channels or not guild.me.guild_permissions.move_members:
            return await reply(interaction, "Botun **Kanalları Yönet** ve **Üyeleri Taşı** izinleri olmalı.", ok=False)
        category = category or await guild.create_category("🔊 Temp Voice")
        hub = await guild.create_voice_channel("➕ Join to Create", category=category)
        await self.bot.settings.set(guild.id, K + "hub", hub.id)
        await reply(interaction, f"Hazır: {hub.mention} kanalına giren herkese kendi odası açılacak.")
