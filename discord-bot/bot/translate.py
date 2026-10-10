from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

import aiohttp

log = logging.getLogger(__name__)

# Google Translate'in anahtarsız web uç noktası: ücretsiz, hesap gerektirmez.
_URL = "https://translate.googleapis.com/translate_a/single"
_MAX_CHARS = 4500
_BATCH_CHARS = 3500
_CACHE_SIZE = 4000


class Translator:
    """Ücretsiz çeviri. Hata olursa orijinal metni döndürür (bot asla bu yüzden durmaz)."""

    def __init__(self, enabled: bool, max_concurrency: int = 4) -> None:
        self.enabled = enabled
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(max_concurrency)
        self._cache: OrderedDict[tuple[str, str], tuple[str, str]] = OrderedDict()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    def _remember(self, key: tuple[str, str], value: tuple[str, str]) -> None:
        self._cache[key] = value
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)

    async def translate(self, text: str, target: str = "en") -> tuple[str, str]:
        """(çeviri, kaynak_dil) döndürür. Kaynak dil bilinmiyorsa '?'."""
        text = text.strip()
        if not self.enabled or not text:
            return text, "?"
        key = (target, text)
        if (cached := self._cache.get(key)) is not None:
            self._cache.move_to_end(key)
            return cached
        result = await self._request(text[:_MAX_CHARS], target)
        if result is None:
            return text, "?"
        self._remember(key, result)
        return result

    async def translate_batch(self, texts: list[str], target: str = "en") -> list[str]:
        """Çok sayıda kısa metni satır satır birleştirip az istekle çevirir.

        Satır sayısı tutmazsa (çeviri satırları birleştirdiyse) o grup tek tek çevrilir.
        """
        if not self.enabled:
            return list(texts)
        lines = [" ".join(t.split()) for t in texts]  # her metin tek satır olmalı
        groups: list[list[int]] = []
        size = 0
        for i, line in enumerate(lines):
            if not groups or size + len(line) + 1 > _BATCH_CHARS:
                groups.append([])
                size = 0
            groups[-1].append(i)
            size += len(line) + 1

        out = list(lines)

        async def run(indices: list[int]) -> None:
            chunk = "\n".join(lines[i] for i in indices)
            result = await self._request(chunk[:_MAX_CHARS], target) if chunk.strip() else None
            parts = result[0].split("\n") if result else []
            if len(parts) == len(indices):
                for i, part in zip(indices, parts):
                    out[i] = part.strip() or lines[i]
            else:
                singles = await asyncio.gather(*(self.translate(lines[i], target) for i in indices))
                for i, (translated, _) in zip(indices, singles):
                    out[i] = translated

        await asyncio.gather(*(run(g) for g in groups))
        return out

    async def _request(self, text: str, target: str) -> tuple[str, str] | None:
        params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
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
