from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..music import GuildPlayer, LoopMode, search_tracks
from ..util import clip, embed, reply

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

EMPTY_CHANNEL_GRACE = 60.0


class Music(commands.Cog):
    """Jockie Music / Rythm: YouTube ve yt-dlp'nin desteklediği sitelerden müzik çalma."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}
        self._empty_timers: dict[int, asyncio.Task[None]] = {}

    async def cog_unload(self) -> None:
        for player in list(self.players.values()):
            await player.destroy()
        for t in self._empty_timers.values():
            t.cancel()

    # ---------- Ortak kontroller ----------

    @staticmethod
    def _user_channel(interaction: discord.Interaction) -> discord.VoiceChannel | discord.StageChannel | None:
        member = interaction.user
        if isinstance(member, discord.Member) and member.voice and member.voice.channel:
            return member.voice.channel
        return None

    async def _player_for_control(self, interaction: discord.Interaction) -> GuildPlayer | None:
        """Kontrol komutları sadece botla aynı ses kanalındakiler tarafından kullanılabilir."""
        assert interaction.guild is not None
        player = self.players.get(interaction.guild.id)
        if player is None or player.voice is None:
            await reply(interaction, "I'm not playing anything.", ok=False)
            return None
        if self._user_channel(interaction) != player.voice.channel:
            await reply(interaction, "You need to be in my voice channel.", ok=False)
            return None
        return player

    # ---------- Boş kanaldan otomatik ayrılma ----------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        player = self.players.get(member.guild.id)
        if player is None or player.voice is None:
            return
        channel = player.voice.channel
        humans = [m for m in channel.members if not m.bot]
        gid = member.guild.id
        if not humans and gid not in self._empty_timers:
            self._empty_timers[gid] = asyncio.create_task(self._leave_if_still_empty(gid))
        elif humans and gid in self._empty_timers:
            self._empty_timers.pop(gid).cancel()

    async def _leave_if_still_empty(self, guild_id: int) -> None:
        try:
            await asyncio.sleep(EMPTY_CHANNEL_GRACE)
            player = self.players.get(guild_id)
            if player and player.voice and not [m for m in player.voice.channel.members if not m.bot]:
                await player.destroy()
        finally:
            self._empty_timers.pop(guild_id, None)

    # ---------- Komutlar ----------

    @app_commands.command(name="play", description="Play a song or playlist (name or link)")
    @app_commands.describe(query="Song name, YouTube/SoundCloud link or playlist link")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def play(self, interaction: discord.Interaction, query: app_commands.Range[str, 1, 300]) -> None:
        guild = interaction.guild
        assert guild is not None
        channel = self._user_channel(interaction)
        if channel is None:
            return await reply(interaction, "Join a voice channel first.", ok=False)
        perms = channel.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            return await reply(interaction, "I can't join or speak in your voice channel.", ok=False)
        player = self.players.get(guild.id)
        if player and player.voice and player.voice.channel != channel:
            return await reply(interaction, f"I'm already playing in {player.voice.channel.mention}.", ok=False)

        await interaction.response.defer(thinking=True)
        try:
            tracks = await asyncio.to_thread(search_tracks, query, interaction.user.id)
        except Exception as e:  # yt-dlp: bulunamadı, bölge kısıtı, vb.
            log.info("Arama başarısız (%s): %s", query, e)
            return await reply(interaction, "I couldn't find or load that.", ok=False)
        if not tracks:
            return await reply(interaction, "No results.", ok=False)

        if guild.voice_client is None:
            try:
                await channel.connect(self_deaf=True)
            except (discord.ClientException, asyncio.TimeoutError, RuntimeError) as e:
                log.warning("Ses kanalına bağlanılamadı: %s", e)
                return await reply(interaction, "I couldn't connect to the voice channel.", ok=False)
        if player is None or player.voice is None:
            text_channel = interaction.channel
            assert isinstance(text_channel, discord.abc.Messageable)
            player = GuildPlayer(self.bot, guild, text_channel)
            self.players[guild.id] = player

        added = player.add(tracks)
        if added == 0:
            return await reply(interaction, "The queue is full.", ok=False)
        if len(tracks) == 1:
            await reply(interaction, f"➕ Added **{clip(tracks[0].title, 200)}** `{tracks[0].duration_text}`", ephemeral=False)
        else:
            await reply(interaction, f"➕ Added **{added}** tracks to the queue.", ephemeral=False)

    @app_commands.command(name="skip", description="Skip the current song")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        if player := await self._player_for_control(interaction):
            player.skip()
            await reply(interaction, "⏭️ Skipped.", ephemeral=False)

    @app_commands.command(name="stop", description="Stop the music, clear the queue and leave")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        if player := await self._player_for_control(interaction):
            await player.destroy()
            await reply(interaction, "⏹️ Stopped.", ephemeral=False)

    @app_commands.command(name="pause", description="Pause the music")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        if (player := await self._player_for_control(interaction)) and player.voice:
            player.voice.pause()
            await reply(interaction, "⏸️ Paused.", ephemeral=False)

    @app_commands.command(name="resume", description="Resume the music")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        if (player := await self._player_for_control(interaction)) and player.voice:
            player.voice.resume()
            await reply(interaction, "▶️ Resumed.", ephemeral=False)

    @app_commands.command(name="queue", description="Show the queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.players.get(interaction.guild.id)
        if player is None or (player.current is None and not player.queue):
            return await reply(interaction, "The queue is empty.")
        lines = []
        if player.current:
            lines.append(f"**Now:** {clip(player.current.title, 80)} `{player.current.duration_text}`\n")
        lines += [f"`{i}.` {clip(t.title, 80)} `{t.duration_text}`" for i, t in enumerate(list(player.queue)[:15], 1)]
        if len(player.queue) > 15:
            lines.append(f"…and {len(player.queue) - 15} more")
        e = embed(f"🎵 Queue · {len(player.queue)} tracks", "\n".join(lines))
        e.set_footer(text=f"Loop: {player.loop_mode} · Volume: {int(player.volume * 100)}%")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="nowplaying", description="Show the current song")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        player = self.players.get(interaction.guild.id)
        if player is None or player.current is None:
            return await reply(interaction, "Nothing is playing.")
        t = player.current
        await interaction.response.send_message(
            embed=embed("🎶 Now playing", f"[{clip(t.title, 200)}]({t.url}) `{t.duration_text}`\nRequested by <@{t.requester_id}>"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="volume", description="Set the volume (0-150%)")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 150]) -> None:
        if player := await self._player_for_control(interaction):
            player.set_volume(percent)
            await reply(interaction, f"🔊 Volume: {percent}%", ephemeral=False)

    @app_commands.command(name="loop", description="Loop mode")
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction, mode: LoopMode) -> None:
        if player := await self._player_for_control(interaction):
            if mode not in ("off", "track", "queue"):
                return await reply(interaction, "Invalid mode.", ok=False)
            player.loop_mode = mode
            await reply(interaction, f"🔁 Loop: **{mode}**", ephemeral=False)

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if player := await self._player_for_control(interaction):
            player.shuffle()
            await reply(interaction, "🔀 Queue shuffled.", ephemeral=False)

    @app_commands.command(name="remove", description="Remove a song from the queue by its number")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, 500]) -> None:
        if not (player := await self._player_for_control(interaction)):
            return
        if position > len(player.queue):
            return await reply(interaction, "There's no song at that position.", ok=False)
        track = player.queue[position - 1]
        del player.queue[position - 1]
        await reply(interaction, f"🗑️ Removed **{clip(track.title, 200)}**.", ephemeral=False)
