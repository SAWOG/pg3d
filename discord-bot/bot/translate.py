from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

import aiohttp

log = logging.getLogger(__name__)

# Google Translate'in anahtarsız web uç noktası: ücretsiz, hesap gerektirmez.
_URL = "https://translate.googleapis.com/translate_a/single"
_MAX_CHARS = 4500
_CACHE_SIZE = 2000


class Translator:
    """Metni Türkçeye çevirir; hata olursa orijinal metni döndürür (bot asla bu yüzden durmaz)."""

    def __init__(self, enabled: bool, target: str = "tr", max_concurrency: int = 4) -> None:
        self.enabled = enabled
        self._target = target
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(max_concurrency)
        self._cache: OrderedDict[str, tuple[str, str]] = OrderedDict()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def translate(self, text: str) -> tuple[str, str]:
        """(çeviri, kaynak_dil) döndürür. Kaynak dil bilinmiyorsa '?'."""
        text = text.strip()
        if not self.enabled or not text:
            return text, "?"
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            return cached

        result = await self._request(text[:_MAX_CHARS])
        if result is None:
            return text, "?"
        self._cache[text] = result
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return result

    async def translate_many(self, texts: list[str]) -> list[tuple[str, str]]:
        return list(await asyncio.gather(*(self.translate(t) for t in texts)))

    async def _request(self, text: str) -> tuple[str, str] | None:
        params = {"client": "gtx", "sl": "auto", "tl": self._target, "dt": "t", "q": text}
        async with self._sem:
            try:
                async with self._get_session().get(_URL, params=params) as resp:
                    if resp.status != 200:
                        log.warning("Çeviri başarısız: HTTP %s", resp.status)
                        return None
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                log.warning("Çeviri başarısız: %s", e)
                return None
        try:
            translated = "".join(part[0] for part in data[0] if part and part[0])
            source = str(data[2]) if len(data) > 2 and data[2] else "?"
        except (TypeError, IndexError, KeyError):
            log.warning("Çeviri yanıtı beklenmeyen formatta")
            return None
        return (translated or text), source
