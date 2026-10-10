from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..util import clip, embed, manage_guild_only, reply
from ..youtube_feed import FeedError, fetch_feed, new_videos, resolve_channel_id

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

MAX_SUBS = 30
DEFAULT_MESSAGE = "📺 **{channel}** uploaded a new video!\n{link}"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_subs (
    guild_id      INTEGER NOT NULL,
    yt_channel_id TEXT    NOT NULL,
    channel_name  TEXT    NOT NULL,
    discord_channel_id INTEGER NOT NULL,
    last_video_id TEXT,
    message       TEXT    NOT NULL,
    ping_role_id  INTEGER,
    PRIMARY KEY (guild_id, yt_channel_id)
);
"""


class YouTube(commands.Cog):
    """YouTube Alert: kanallara yeni video gelince bildirim (API anahtarı gerekmez, RSS kullanılır)."""

    youtube = app_commands.Group(
        name="youtube", description="YouTube bildirimleri", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._sem = asyncio.Semaphore(4)

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()

    @tasks.loop(minutes=10)
    async def poll_loop(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT guild_id, yt_channel_id, channel_name, discord_channel_id, last_video_id, message, ping_role_id FROM yt_subs"
        )
        await asyncio.gather(*(self._check(*row) for row in rows), return_exceptions=True)

    @poll_loop.before_loop
    async def _wait(self) -> None:
        await self.bot.wait_until_ready()

    async def _check(self, guild_id: int, yt_id: str, name: str, channel_id: int, last: str | None,
                     message: str, role_id: int | None) -> None:
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if guild is None or not isinstance(channel, discord.TextChannel):
            return
        async with self._sem:
            try:
                feed = await fetch_feed(self.bot.http_session, yt_id)
            except FeedError as e:
                log.info("YouTube feed alınamadı (%s): %s", yt_id, e)
                return
        videos = new_videos(feed, last)
        if not videos:
            return
        role = guild.get_role(role_id) if role_id else None
        for video in videos:
            text = (message.replace("{channel}", feed.channel_name).replace("{title}", video.title)
                    .replace("{link}", video.link))
            if role is not None:
                text = f"{role.mention} {text}"
            try:
                await channel.send(text[:2000],
                                   allowed_mentions=discord.AllowedMentions(roles=[role] if role else False, users=False, everyone=False))
            except discord.HTTPException as e:
                log.warning("YouTube bildirimi gönderilemedi: %s", e)
                return
        await self.bot.db.execute(
            "UPDATE yt_subs SET last_video_id = ?, channel_name = ? WHERE guild_id = ? AND yt_channel_id = ?",
            (feed.videos[0].video_id, feed.channel_name, guild_id, yt_id),
        )

    @youtube.command(name="add", description="Bir YouTube kanalını takip et")
    @app_commands.describe(youtube_channel="Kanal linki, @kullanıcıadı veya UC... ID", channel="Bildirimin gideceği kanal",
                           ping_role="Etiketlenecek rol (opsiyonel)", message="Mesaj: {channel} {title} {link}")
    @manage_guild_only()
    async def add(self, interaction: discord.Interaction, youtube_channel: str, channel: discord.TextChannel,
                  ping_role: discord.Role | None = None, message: str | None = None) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        row = await self.bot.db.fetchone("SELECT COUNT(*) FROM yt_subs WHERE guild_id = ?", (gid,))
        if row and int(row[0]) >= MAX_SUBS:
            return await reply(interaction, f"En fazla {MAX_SUBS} kanal takip edilebilir.", ok=False)
        if ping_role is not None and (ping_role.is_default() or ping_role.managed):
            return await reply(interaction, "Bu rol etiketlenemez.", ok=False)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            yt_id = await resolve_channel_id(self.bot.http_session, youtube_channel)
            feed = await fetch_feed(self.bot.http_session, yt_id)
        except FeedError as e:
            return await reply(interaction, str(e), ok=False)
        last = feed.videos[0].video_id if feed.videos else None  # eski videolar duyurulmaz
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO yt_subs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, yt_id, feed.channel_name, channel.id, last, clip(message, 1000) if message else DEFAULT_MESSAGE,
             ping_role.id if ping_role else None),
        )
        await reply(interaction, f"📺 **{feed.channel_name}** takip ediliyor → {channel.mention} (10 dakikada bir kontrol).")

    @youtube.command(name="remove", description="Takibi bırak")
    @app_commands.describe(youtube_channel="Kanal adı veya UC... ID (/youtube list'te görünen)")
    @manage_guild_only()
    async def remove(self, interaction: discord.Interaction, youtube_channel: str) -> None:
        assert interaction.guild is not None
        n = await self.bot.db.execute(
            "DELETE FROM yt_subs WHERE guild_id = ? AND (yt_channel_id = ? OR channel_name = ?)",
            (interaction.guild.id, youtube_channel.strip(), youtube_channel.strip()),
        )
        await reply(interaction, "Takip bırakıldı." if n else "Böyle bir takip yok.", ok=bool(n))

    @youtube.command(name="list", description="Takip edilen kanallar")
    @manage_guild_only()
    async def list_subs(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = await self.bot.db.fetchall(
            "SELECT channel_name, yt_channel_id, discord_channel_id FROM yt_subs WHERE guild_id = ?", (interaction.guild.id,)
        )
        text = "\n".join(f"**{n}** (`{y}`) → <#{c}>" for n, y, c in rows) or "Takip edilen kanal yok."
        await interaction.response.send_message(embed=embed("📺 YouTube bildirimleri", text), ephemeral=True)
