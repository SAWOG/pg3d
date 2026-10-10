from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_ID_IN_URL_RE = re.compile(r"/channel/(UC[\w-]{22})")
_ID_IN_PAGE_RE = re.compile(r'"(?:externalId|channelId|browseId)":"(UC[\w-]{22})"')
_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
# AB'de çıkan çerez onay sayfasını atlamak için
_HEADERS = {"Cookie": "CONSENT=YES+cb; SOCS=CAI", "Accept-Language": "en-US,en;q=0.9"}
_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


@dataclass(frozen=True, slots=True)
class Video:
    video_id: str
    title: str
    link: str


@dataclass(frozen=True, slots=True)
class Feed:
    channel_name: str
    videos: list[Video]  # en yeniden eskiye


class FeedError(Exception):
    pass


async def resolve_channel_id(session: aiohttp.ClientSession, text: str) -> str:
    """Kanal ID'si, /channel/ linki, @handle veya youtube.com linkinden kanal ID'sini bulur."""
    text = text.strip()
    if _CHANNEL_ID_RE.match(text):
        return text
    if m := _ID_IN_URL_RE.search(text):
        return m.group(1)
    if text.startswith("@"):
        url = f"https://www.youtube.com/{text}"
    else:
        url = text if text.startswith(("http://", "https://")) else f"https://{text}"
        # Sadece YouTube'a istek atılır (botun rastgele adreslere istek atması engellenir)
        if (urlparse(url).hostname or "").lower() not in _ALLOWED_HOSTS:
            raise FeedError("Bu bir YouTube kanal linki değil.")
    try:
        async with session.get(url, headers=_HEADERS) as resp:
            if resp.status != 200:
                raise FeedError(f"YouTube sayfası açılamadı (HTTP {resp.status}).")
            page = await resp.text()
    except aiohttp.ClientError as e:
        raise FeedError("YouTube'a bağlanılamadı.") from e
    if m := _ID_IN_PAGE_RE.search(page):
        return m.group(1)
    raise FeedError("Kanal bulunamadı. Kanalın /channel/UC... linkini dene.")


def parse_feed(xml_text: str) -> Feed:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise FeedError("Feed okunamadı.") from e
    name = root.findtext("a:title", default="YouTube", namespaces=_NS)
    videos: list[Video] = []
    for entry in root.findall("a:entry", _NS):
        vid = entry.findtext("yt:videoId", namespaces=_NS)
        title = entry.findtext("a:title", default="", namespaces=_NS)
        if vid:
            videos.append(Video(vid, title, f"https://www.youtube.com/watch?v={vid}"))
    return Feed(name, videos)


async def fetch_feed(session: aiohttp.ClientSession, channel_id: str) -> Feed:
    if not _CHANNEL_ID_RE.match(channel_id):
        raise FeedError("Geçersiz kanal ID'si.")
    try:
        async with session.get(FEED_URL.format(channel_id), headers=_HEADERS) as resp:
            if resp.status != 200:
                raise FeedError(f"Feed alınamadı (HTTP {resp.status}).")
            return parse_feed(await resp.text())
    except aiohttp.ClientError as e:
        raise FeedError("YouTube'a bağlanılamadı.") from e


def new_videos(feed: Feed, last_video_id: str | None, limit: int = 3) -> list[Video]:
    """Son duyurulandan sonraki videolar, eskiden yeniye. Son video feed'de yoksa sadece en yeniyi döndürür."""
    if not feed.videos or feed.videos[0].video_id == last_video_id:
        return []
    ids = [v.video_id for v in feed.videos]
    if last_video_id in ids:
        fresh = feed.videos[: ids.index(last_video_id)]
    else:
        fresh = feed.videos[:1]  # eski video silinmiş olabilir: spam yerine sadece en yeni
    return list(reversed(fresh[:limit]))
