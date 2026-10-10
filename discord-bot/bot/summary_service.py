"""/summary komutu ve terminal aracının ortak kullandığı özet akışı."""
from __future__ import annotations

import discord

from .chat_digest import Digest, RawMessage, finalize, summarize
from .translate import Translator

ALL_LIMIT = 1000
LANGUAGES: dict[str, str] = {"en": "English", "tr": "Türkçe", "pt": "Português", "es": "Español"}
_CONTENT_TYPES = (discord.MessageType.default, discord.MessageType.reply)


def parse_count(text: str) -> int | None:
    text = text.strip().lower()
    if text in ("all", "hepsi", "tümü", "tumu"):
        return ALL_LIMIT
    return min(int(text), ALL_LIMIT) if text.isdigit() and int(text) > 0 else None


async def build_digest(channel: discord.abc.Messageable, count: int, translator: Translator, lang: str) -> Digest | None:
    """Kanalın son `count` mesajını okuyup çevrilmiş özet döndürür. Özetlenecek mesaj yoksa None."""
    raw: list[RawMessage] = []
    async for m in channel.history(limit=count):
        if m.author.bot or m.type not in _CONTENT_TYPES:
            continue
        raw.append(RawMessage(m.author.id, m.author.display_name, m.clean_content, m.created_at, len(m.attachments)))
    if not raw:
        return None
    raw.reverse()  # history en yeniden eskiye döner; özet eskiden yeniye okunur
    digest = summarize(raw)
    translations = await translator.translate_batch([b.text for b in digest.blocks], lang if lang in LANGUAGES else "en")
    for block, text in zip(digest.blocks, translations):
        block.english = text
    return finalize(digest)
