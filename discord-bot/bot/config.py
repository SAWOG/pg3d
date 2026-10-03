from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _ids(name: str) -> frozenset[int]:
    raw = os.getenv(name, "")
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _words(name: str) -> frozenset[str]:
    raw = os.getenv(name, "")
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "evet"}


def _read_word_list(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return tuple(ln for ln in lines if ln and not ln.startswith("#"))


@dataclass(frozen=True, slots=True)
class Config:
    discord_token: str
    guild_id: int
    report_channel_id: int
    translate_enabled: bool
    suggestion_channel_id: int
    ticket_category_ids: frozenset[int]
    ticket_prefix: str
    ticket_auto_summary_delay: int
    daily_summary_time: time
    moderation_enabled: bool
    mod_log_channel_id: int
    mod_ignored_channel_ids: frozenset[int]
    mod_exempt_role_ids: frozenset[int]
    banned_words: tuple[str, ...]
    block_invites: bool
    block_links: bool
    allowed_link_domains: frozenset[str]
    max_mentions: int
    spam_messages: int
    spam_seconds: int
    duplicate_limit: int
    caps_min_length: int
    mention_guard_channel_ids: frozenset[int]
    mention_guard_user_ids: frozenset[int]
    mention_guard_names: frozenset[str]
    mention_guard_message: str
    mention_guard_cooldown: int
    mention_guard_delete_after: int
    warn_timeout_threshold: int
    timeout_minutes: int
    warn_expire_days: int
    db_path: Path

    @classmethod
    def load(cls) -> Config:
        load_dotenv(ROOT / ".env")

        tz = ZoneInfo(os.getenv("TIMEZONE", "Europe/Istanbul"))
        hh, mm = (int(p) for p in os.getenv("DAILY_SUMMARY_TIME", "21:00").split(":"))

        report = _int("REPORT_CHANNEL_ID")
        if not report:
            raise RuntimeError("REPORT_CHANNEL_ID .env içinde tanımlı değil")

        return cls(
            discord_token=_req("DISCORD_TOKEN"),
            guild_id=_int("GUILD_ID"),
            report_channel_id=report,
            translate_enabled=_bool("TRANSLATE_ENABLED", True),
            suggestion_channel_id=_int("SUGGESTION_CHANNEL_ID"),
            ticket_category_ids=_ids("TICKET_CATEGORY_IDS"),
            ticket_prefix=os.getenv("TICKET_CHANNEL_PREFIX", "ticket-").strip().lower(),
            ticket_auto_summary_delay=_int("TICKET_AUTO_SUMMARY_DELAY", 300),
            daily_summary_time=time(hh, mm, tzinfo=tz),
            moderation_enabled=_bool("MODERATION_ENABLED", True),
            mod_log_channel_id=_int("MOD_LOG_CHANNEL_ID") or report,
            mod_ignored_channel_ids=_ids("MOD_IGNORED_CHANNEL_IDS"),
            mod_exempt_role_ids=_ids("MOD_EXEMPT_ROLE_IDS"),
            banned_words=_read_word_list(ROOT / "banned_words.txt"),
            block_invites=_bool("BLOCK_INVITES", True),
            block_links=_bool("BLOCK_LINKS", False),
            allowed_link_domains=_words("ALLOWED_LINK_DOMAINS"),
            max_mentions=max(1, _int("MAX_MENTIONS", 5)),
            spam_messages=max(2, _int("SPAM_MESSAGES", 6)),
            spam_seconds=max(1, _int("SPAM_SECONDS", 5)),
            duplicate_limit=max(1, _int("DUPLICATE_LIMIT", 3)),
            caps_min_length=max(5, _int("CAPS_MIN_LENGTH", 15)),
            mention_guard_channel_ids=_ids("MENTION_GUARD_CHANNEL_IDS"),
            mention_guard_user_ids=_ids("MENTION_GUARD_USER_IDS"),
            mention_guard_names=_words("MENTION_GUARD_NAMES"),
            mention_guard_message=os.getenv(
                "MENTION_GUARD_MESSAGE", "{user} lütfen sawog'u etiketleme, sorunun için ticket aç."
            ).replace("\\n", "\n"),
            mention_guard_cooldown=max(0, _int("MENTION_GUARD_COOLDOWN", 60)),
            mention_guard_delete_after=max(0, _int("MENTION_GUARD_DELETE_AFTER", 0)),
            warn_timeout_threshold=max(1, _int("WARN_TIMEOUT_THRESHOLD", 3)),
            timeout_minutes=max(1, _int("TIMEOUT_MINUTES", 30)),
            warn_expire_days=max(1, _int("WARN_EXPIRE_DAYS", 30)),
            db_path=ROOT / "bot.db",
        )
