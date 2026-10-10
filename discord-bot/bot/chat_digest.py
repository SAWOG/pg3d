"""Yapay zekasız sohbet özeti: boş mesajları ayıklar, art arda mesajları birleştirir, konu ve soruları çıkarır."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MERGE_GAP = timedelta(minutes=5)

# Bilgi taşımayan kısa mesajlar (EN / TR / PT)
FILLER = frozenset({
    "ok", "okay", "oke", "oki", "k", "kk", "lol", "lmao", "lmfao", "xd", "ty", "thx", "thanks", "np", "yes", "no", "ya",
    "ye", "yep", "yup", "nope", "hm", "hmm", "oh", "ah", "wow", "gg", "bruh", "nice", "cool", "hi", "hello", "hey", "yo",
    "sa", "as", "selam", "tamam", "tmm", "evet", "hayir", "he", "yok", "aynen", "iyi", "sim", "nao", "oi", "ola", "blz",
    "vlw", "obg", "tmj", "rs", "kkk", "pls", "plz", "idk", "same", "true", "fr", "ikr", "omg",
})
_FILLER_RE = re.compile(r"^(?:k{2,}|(?:ha){2,}h?|(?:he){2,}|(?:xd)+|(?:rs)+|l+o+l+|a+h+|o+k+|s+k+s+)$")
_WORD_RE = re.compile(r"[a-z][a-z']{2,}")
_TR_FOLD = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "ã": "a", "õ": "o"})

STOPWORDS = frozenset("""
the and for are but not you all any can had her was one our out day get has him his how man new now old see two way
who boy did its let put say she too use that with have this will your from they know want been good much some time
very when come here just like long make many more only over such take than them well were what into year then also
back after use two how our work first well even want because any these give most us is it to of in a an on at be as
by or if so do my me we he i im dont its thats yes no ok okay oh yeah yea lol can't cant didn't didnt doesn't doesnt
there their about would could should which where while being does done going gonna really still something anyone
someone people thing things think need please guys guy hello hey thanks thank sorry why what's whats ive i'm you're
youre he's hes she's shes we're were they're theyre isn't isnt aren't arent wasn't wasnt won't wont let's lets
""".split())


@dataclass(slots=True)
class RawMessage:
    author_id: int
    author: str
    text: str
    created_at: datetime
    attachments: int = 0


@dataclass(slots=True)
class Block:
    author_id: int
    author: str
    parts: list[str]
    start: datetime
    end: datetime
    count: int = 1
    english: str = ""

    @property
    def text(self) -> str:
        return " · ".join(self.parts)


@dataclass(slots=True)
class Digest:
    blocks: list[Block]
    total: int
    skipped: int
    participants: list[tuple[str, int]]
    start: datetime | None
    end: datetime | None
    topics: list[str] = field(default_factory=list)
    questions: list[tuple[str, str]] = field(default_factory=list)  # (yazar, soru)


def is_filler(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.lower().translate(_TR_FOLD)).strip()
    if not cleaned:
        return True  # sadece emoji / noktalama
    words = cleaned.split()
    return all(w in FILLER or _FILLER_RE.match(w) for w in words) and len(words) <= 3


def build_blocks(messages: list[RawMessage]) -> tuple[list[Block], int]:
    """Eskiden yeniye sıralı mesajlardan bloklar üretir. (bloklar, atlanan_mesaj_sayısı)"""
    blocks: list[Block] = []
    skipped = 0
    for m in messages:
        text = " ".join(m.text.split())
        if not text and m.attachments:
            text = "[image]" if m.attachments == 1 else f"[{m.attachments} files]"
        if not text or (not m.attachments and is_filler(text)):
            skipped += 1
            continue
        last = blocks[-1] if blocks else None
        if last and last.author_id == m.author_id and m.created_at - last.end <= MERGE_GAP:
            last.parts.append(text)
            last.end = m.created_at
            last.count += 1
        else:
            blocks.append(Block(m.author_id, m.author, [text], m.created_at, m.created_at))
    return blocks, skipped


def top_topics(blocks: list[Block], limit: int = 8) -> list[str]:
    """İngilizce metinlerde en çok geçen anlamlı kelimeler. Her blok bir kez sayılır (tek kişinin spam'i baskın olmasın)."""
    counts: Counter[str] = Counter()
    for b in blocks:
        words = {w.strip("'") for w in _WORD_RE.findall(b.english.lower())}
        counts.update(w for w in words if w not in STOPWORDS and len(w) > 2)
    return [w for w, n in counts.most_common(limit) if n >= 2]


def find_questions(blocks: list[Block], limit: int = 6) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for b in blocks:
        for sentence in re.split(r"(?<=[.!?])\s+", b.english):
            if sentence.rstrip().endswith("?") and len(sentence) > 8:
                out.append((b.author, sentence.strip()))
    return out[-limit:]  # en son sorulanlar


def summarize(messages: list[RawMessage]) -> Digest:
    blocks, skipped = build_blocks(messages)
    participants = Counter(m.author for m in messages).most_common()
    return Digest(
        blocks=blocks,
        total=len(messages),
        skipped=skipped,
        participants=participants,
        start=messages[0].created_at if messages else None,
        end=messages[-1].created_at if messages else None,
    )


def finalize(digest: Digest) -> Digest:
    """Bloklar çevrildikten sonra konu ve soruları çıkarır."""
    digest.topics = top_topics(digest.blocks)
    digest.questions = find_questions(digest.blocks)
    return digest
