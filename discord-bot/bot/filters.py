from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import Literal

from .config import Config

Severity = Literal["low", "medium", "high"]

_INVITE_RE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg|dsc\.gg)/[\w-]+", re.I)
_LINK_RE = re.compile(r"https?://([^\s/<>]+)", re.I)
# Leetspeak / ayırıcı ile filtre atlatmayı zorlaştırmak için normalizasyon tablosu
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_TR_FOLD = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    reason: str
    severity: Severity
    delete: bool


def normalize(text: str) -> str:
    text = text.translate(_TR_FOLD).lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.translate(_LEET)
    return _NON_ALNUM.sub("", text)


class _UserState:
    __slots__ = ("times", "last_text", "repeat", "touched")

    def __init__(self) -> None:
        self.times: deque[float] = deque()
        self.last_text = ""
        self.repeat = 0
        self.touched = 0.0


class RuleFilter:
    """Kural kontrolleri. Mesaj başına O(kelime sayısı); durum sadece aktif kullanıcılar için tutulur."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._banned_words = frozenset(normalize(w) for w in cfg.banned_words if normalize(w))
        # Boşluk içeren yasaklı ifadeler (ör. "hesap satilik") alt dize olarak aranır
        self._banned_phrases = tuple(p for p in self._banned_words if " " in p)
        self._allowed_domains = cfg.allowed_link_domains
        self._state: dict[int, _UserState] = {}

    def prune(self, max_idle: float = 600.0) -> None:
        cutoff = time.monotonic() - max_idle
        stale = [uid for uid, st in self._state.items() if st.touched < cutoff]
        for uid in stale:
            del self._state[uid]

    def check(self, user_id: int, content: str, mention_count: int, *, is_edit: bool = False) -> Violation | None:
        cfg = self._cfg
        now = time.monotonic()
        st = self._state.setdefault(user_id, _UserState())
        st.touched = now

        norm = normalize(content)
        if not is_edit:  # düzenlemeler hız/tekrar sayacına girmez, sadece içerik kontrol edilir
            # Spam: kısa sürede çok mesaj
            st.times.append(now)
            while st.times and now - st.times[0] > cfg.spam_seconds:
                st.times.popleft()
            if len(st.times) > cfg.spam_messages:
                st.times.clear()
                return Violation("Spam", f"{cfg.spam_seconds} saniyede çok fazla mesaj gönderdin.", "medium", True)

            # Aynı mesajı tekrar tekrar gönderme
            if norm and norm == st.last_text:
                st.repeat += 1
            else:
                st.last_text, st.repeat = norm, 1
            if st.repeat > cfg.duplicate_limit:
                st.repeat = 0
                return Violation("Flood", "Aynı mesajı tekrar tekrar gönderme.", "low", True)

        if mention_count > cfg.max_mentions:
            return Violation("Toplu etiket", f"Bir mesajda en fazla {cfg.max_mentions} kişi etiketleyebilirsin.", "medium", True)

        if cfg.block_invites and _INVITE_RE.search(content):
            return Violation("Reklam", "Sunucu davet linki paylaşmak yasak.", "medium", True)

        if cfg.block_links:
            for host in _LINK_RE.findall(content):
                host = host.lower().split(":")[0]
                if not any(host == d or host.endswith("." + d) for d in self._allowed_domains):
                    return Violation("Link", "İzin verilmeyen link paylaştın.", "low", True)

        if self._banned_words:
            words = norm.split()
            squashed = norm.replace(" ", "")
            if any(w in self._banned_words for w in words) or any(p in norm for p in self._banned_phrases) \
                    or any(len(w) >= 5 and w in squashed for w in self._banned_words if " " not in w):
                return Violation("Uygunsuz dil", "Mesajında yasaklı kelime var.", "medium", True)

        letters = [c for c in content if c.isalpha()]
        if len(letters) >= cfg.caps_min_length and sum(c.isupper() for c in letters) / len(letters) >= 0.8:
            return Violation("Büyük harf", "Lütfen tamamen büyük harfle yazma.", "low", False)

        return None
