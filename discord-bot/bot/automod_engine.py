from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass

_INVITE_RE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg|dsc\.gg)/[\w-]+", re.I)
_LINK_RE = re.compile(r"https?://([^\s/<>]+)", re.I)
# Leetspeak / Türkçe karakter ile filtre atlatmayı zorlaştırmak için normalizasyon
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_TR_FOLD = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")

SPAM_MESSAGES = 6
SPAM_SECONDS = 5.0
DUPLICATE_LIMIT = 3
CAPS_MIN_LENGTH = 15


def normalize(text: str) -> str:
    text = text.translate(_TR_FOLD).lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _NON_ALNUM.sub("", text.translate(_LEET))


@dataclass(frozen=True, slots=True)
class Rules:
    invites: bool
    links: bool
    allowed_domains: frozenset[str]
    words: frozenset[str]          # normalize() edilmiş
    max_mentions: int              # 0 = kapalı
    spam: bool
    caps: bool


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    reason: str


class _UserState:
    __slots__ = ("times", "last_text", "repeat", "touched")

    def __init__(self) -> None:
        self.times: deque[float] = deque()
        self.last_text = ""
        self.repeat = 0
        self.touched = 0.0


class AutomodEngine:
    """Mesaj başına O(kelime sayısı); durum sadece son 10 dakikada yazan kullanıcılar için tutulur."""

    def __init__(self) -> None:
        self._state: dict[tuple[int, int], _UserState] = {}

    def prune(self, max_idle: float = 600.0) -> None:
        cutoff = time.monotonic() - max_idle
        for key in [k for k, st in self._state.items() if st.touched < cutoff]:
            del self._state[key]

    def check(self, guild_id: int, user_id: int, content: str, mention_count: int, rules: Rules, *, is_edit: bool = False) -> Violation | None:
        now = time.monotonic()
        st = self._state.setdefault((guild_id, user_id), _UserState())
        st.touched = now
        norm = normalize(content)

        if rules.spam and not is_edit:  # düzenlemeler hız/tekrar sayacına girmez
            st.times.append(now)
            while st.times and now - st.times[0] > SPAM_SECONDS:
                st.times.popleft()
            if len(st.times) > SPAM_MESSAGES:
                st.times.clear()
                return Violation("Spam", "You're sending messages too fast.")
            if norm and norm == st.last_text:
                st.repeat += 1
            else:
                st.last_text, st.repeat = norm, 1
            if st.repeat > DUPLICATE_LIMIT:
                st.repeat = 0
                return Violation("Flood", "Don't repeat the same message.")

        if rules.max_mentions and mention_count > rules.max_mentions:
            return Violation("Mass mention", f"Don't mention more than {rules.max_mentions} people at once.")

        if rules.invites and _INVITE_RE.search(content):
            return Violation("Invite link", "Server invite links aren't allowed.")

        if rules.links:
            for host in _LINK_RE.findall(content):
                host = host.lower().split(":")[0]
                if not any(host == d or host.endswith("." + d) for d in rules.allowed_domains):
                    return Violation("Link", "Links aren't allowed here.")

        if rules.words:
            words = norm.split()
            squashed = norm.replace(" ", "")
            for bad in rules.words:
                if " " in bad:
                    hit = bad in norm
                else:
                    hit = bad in words or (len(bad) >= 5 and bad in squashed)  # "a p t a l" gibi ayırmaları da yakala
                if hit:
                    return Violation("Bad word", "Your message contains a blocked word.")

        if rules.caps:
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= CAPS_MIN_LENGTH and sum(c.isupper() for c in letters) / len(letters) >= 0.8:
                return Violation("Caps", "Please don't type in all caps.")
        return None
