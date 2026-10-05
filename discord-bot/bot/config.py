from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} .env içinde tanımlı değil")
    return value


def _int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _list(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def _ids(name: str) -> frozenset[int]:
    return frozenset(int(x) for x in _list(name))


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "evet"}


def _text(name: str, default: str) -> str:
    return os.getenv(name, default).replace("\\n", "\n")


def _ids_and_names(name: str, default: str) -> tuple[frozenset[int], frozenset[str]]:
    """'123,general-br' gibi listeyi ID'ler ve küçük harfli isimler olarak ayırır."""
    items = _list(name, default)
    ids = frozenset(int(x) for x in items if x.isdigit())
    names = frozenset(x.lstrip("#@").lower() for x in items if not x.isdigit())
    return ids, names


@dataclass(frozen=True, slots=True)
class Config:
    discord_token: str
    guild_id: int
    staff_role_ids: frozenset[int]
    translate_enabled: bool

    # Öneri paneli
    suggestion_channel_id: int
    scan_limit: int
    up_emojis: frozenset[str]
    down_emojis: frozenset[str]
    accept_emoji: str
    reject_emoji: str
    accept_title: str
    reject_title: str
    reason_label: str
    reviewed_by_label: str

    # Etiket uyarısı
    guard_channel_ids: frozenset[int]
    guard_channel_names: frozenset[str]
    guard_target_ids: frozenset[int]
    guard_target_names: frozenset[str]
    guard_message: str
    guard_cooldown: int

    db_path: Path

    @classmethod
    def load(cls) -> Config:
        load_dotenv(ROOT / ".env")
        guard_ch_ids, guard_ch_names = _ids_and_names("MENTION_GUARD_CHANNELS", "general-english,general-br")
        guard_t_ids, guard_t_names = _ids_and_names("MENTION_GUARD_TARGETS", "sawog,admin")

        return cls(
            discord_token=_req("DISCORD_TOKEN"),
            guild_id=_int("GUILD_ID"),
            staff_role_ids=_ids("STAFF_ROLE_IDS"),
            translate_enabled=_bool("TRANSLATE_ENABLED", True),
            suggestion_channel_id=_int("SUGGESTION_CHANNEL_ID"),
            scan_limit=min(10000, max(100, _int("SUGGESTION_SCAN_LIMIT", 3000))),
            up_emojis=frozenset(_list("UP_VOTE_EMOJIS", "👍,⬆️,🔼,✅")),
            down_emojis=frozenset(_list("DOWN_VOTE_EMOJIS", "👎,⬇️,🔽,❌")),
            accept_emoji=os.getenv("ACCEPT_EMOJI", "✅").strip(),
            reject_emoji=os.getenv("REJECT_EMOJI", "❌").strip(),
            accept_title=_text("ACCEPT_TITLE", "✅ Suggestion accepted"),
            reject_title=_text("REJECT_TITLE", "❌ Suggestion rejected"),
            reason_label=_text("REASON_LABEL", "Reason"),
            reviewed_by_label=_text("REVIEWED_BY_LABEL", "Reviewed by"),
            guard_channel_ids=guard_ch_ids,
            guard_channel_names=guard_ch_names,
            guard_target_ids=guard_t_ids,
            guard_target_names=guard_t_names,
            guard_message=_text("MENTION_GUARD_MESSAGE", "Please open a ticket if you need something."),
            guard_cooldown=max(0, _int("MENTION_GUARD_COOLDOWN", 0)),
            db_path=ROOT / "bot.db",
        )
