from __future__ import annotations

import asyncio
import functools
import logging
import random
import shutil
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import discord
import yt_dlp

if TYPE_CHECKING:
    from .main import HelperBot

log = logging.getLogger(__name__)

LoopMode = Literal["off", "track", "queue"]
IDLE_TIMEOUT = 180.0
MAX_QUEUE = 500
MAX_PLAYLIST = 100

_SEARCH_OPTS: dict[str, Any] = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": "in_playlist",  # oynatma listelerinde her video ayrıca çözülmez (hızlı)
    "playlistend": MAX_PLAYLIST,
    "skip_download": True,
}
_STREAM_OPTS: dict[str, Any] = {"format": "bestaudio/best", "quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
_FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"


@functools.lru_cache(maxsize=1)
def ffmpeg_executable() -> str:
    """Sistemde FFmpeg yoksa imageio-ffmpeg paketinin getirdiği hazır FFmpeg kullanılır (Windows'ta kurulum gerektirmez)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as e:  # paket yoksa veya binary bulunamazsa
        raise RuntimeError("FFmpeg bulunamadı. `pip install imageio-ffmpeg` veya FFmpeg kur.") from e


@dataclass(slots=True)
class Track:
    title: str
    url: str
    duration: int
    requester_id: int

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "live"
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _entry_to_track(entry: dict[str, Any], requester_id: int) -> Track | None:
    url = entry.get("webpage_url") or entry.get("url")
    if not isinstance(url, str) or not url.startswith("http"):
        vid = entry.get("id")
        if not isinstance(vid, str):
            return None
        url = f"https://www.youtube.com/watch?v={vid}"
    return Track(str(entry.get("title") or "Unknown"), url, int(entry.get("duration") or 0), requester_id)


def search_tracks(query: str, requester_id: int) -> list[Track]:
    """Bloklayan çağrı: thread içinde çalıştırılır. URL, oynatma listesi veya arama metni kabul eder."""
    q = query.strip()
    if not q.startswith(("http://", "https://")):
        q = f"ytsearch1:{q}"
    with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
        info = ydl.extract_info(q, download=False)
    if not info:
        return []
    entries = info.get("entries")
    if entries is None:
        track = _entry_to_track(info, requester_id)
        return [track] if track else []
    return [t for e in list(entries)[:MAX_PLAYLIST] if e and (t := _entry_to_track(e, requester_id))]


def stream_url(url: str) -> str:
    """Bloklayan çağrı: çalmadan hemen önce taze ses akışı adresi alınır (adresler birkaç saatte geçersizleşir)."""
    with yt_dlp.YoutubeDL(_STREAM_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or "url" not in info:
        raise RuntimeError("No playable stream")
    return str(info["url"])


class GuildPlayer:
    """Bir sunucunun çalma kuyruğu. Tek bir arka plan görevi parçaları sırayla çalar."""

    def __init__(self, bot: HelperBot, guild: discord.Guild, text_channel: discord.abc.Messageable) -> None:
        self.bot = bot
        self.guild = guild
        self.text_channel = text_channel
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.loop_mode: LoopMode = "off"
        self.volume = 0.5
        self._skip_requested = False
        self._wake = asyncio.Event()
        self._finished = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    @property
    def voice(self) -> discord.VoiceClient | None:
        vc = self.guild.voice_client
        return vc if isinstance(vc, discord.VoiceClient) else None

    def add(self, tracks: list[Track]) -> int:
        room = MAX_QUEUE - len(self.queue)
        added = tracks[: max(0, room)]
        self.queue.extend(added)
        self._wake.set()
        return len(added)

    def skip(self) -> None:
        self._skip_requested = True
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()

    def shuffle(self) -> None:
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def set_volume(self, percent: int) -> None:
        self.volume = percent / 100
        if self.voice and isinstance(self.voice.source, discord.PCMVolumeTransformer):
            self.voice.source.volume = self.volume

    async def destroy(self) -> None:
        self.queue.clear()
        if asyncio.current_task() is not self._task:  # görev kendini iptal etmesin (disconnect yarıda kalır)
            self._task.cancel()
        if self.voice:
            await self.voice.disconnect(force=True)
        cog: Any = self.bot.get_cog("Music")
        if cog is not None:
            cog.players.pop(self.guild.id, None)

    async def _announce(self, text: str) -> None:
        try:
            await self.text_channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                if not self.queue:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        await self._announce("👋 Left the voice channel (nothing to play).")
                        await self.destroy()
                        return
                    continue
                track = self.queue.popleft()
                vc = self.voice
                if vc is None or not vc.is_connected():
                    await self.destroy()
                    return
                try:
                    audio_url = await asyncio.to_thread(stream_url, track.url)
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(audio_url, executable=ffmpeg_executable(), before_options=_FFMPEG_BEFORE, options="-vn"),
                        volume=self.volume,
                    )
                except Exception as e:  # yt-dlp/FFmpeg hataları çok çeşitli; parça atlanır, bot durmaz
                    log.warning("Parça çalınamadı (%s): %s", track.url, e)
                    await self._announce(f"⚠️ Couldn't play **{track.title}**, skipping.")
                    continue

                self._finished.clear()
                self._skip_requested = False
                self.current = track
                vc.play(source, after=lambda err: loop.call_soon_threadsafe(self._finished.set))
                await self._announce(f"🎶 Now playing **{track.title}** `{track.duration_text}` · requested by <@{track.requester_id}>")
                await self._finished.wait()
                self.current = None
                if not self._skip_requested:
                    if self.loop_mode == "track":
                        self.queue.appendleft(track)
                    elif self.loop_mode == "queue":
                        self.queue.append(track)
                elif self.loop_mode == "queue":
                    self.queue.append(track)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Müzik çalar hatası")
            await self.destroy()
