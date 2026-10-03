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


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "evet"}


@dataclass(frozen=True, slots=True)
class Config:
    discord_token: str
    guild_id: int
    model: str
    report_channel_id: int
    suggestion_channel_id: int
    ticket_category_ids: frozenset[int]
    ticket_prefix: str
    ticket_auto_summary_delay: int
    daily_summary_time: time
    moderation_enabled: bool
    mod_log_channel_id: int
    mod_ignored_channel_ids: frozenset[int]
    mod_exempt_role_ids: frozenset[int]
    mod_batch_seconds: int
    warn_timeout_threshold: int
    timeout_minutes: int
    warn_expire_days: int
    rules_text: str
    db_path: Path

    @classmethod
    def load(cls) -> Config:
        load_dotenv(ROOT / ".env")
        _req("ANTHROPIC_API_KEY")  # SDK okur; burada sadece erken hata için kontrol

        tz = ZoneInfo(os.getenv("TIMEZONE", "Europe/Istanbul"))
        hh, mm = (int(p) for p in os.getenv("DAILY_SUMMARY_TIME", "21:00").split(":"))

        rules_path = ROOT / "rules.md"
        rules_text = rules_path.read_text(encoding="utf-8").strip()

        report = _int("REPORT_CHANNEL_ID")
        if not report:
            raise RuntimeError("REPORT_CHANNEL_ID .env içinde tanımlı değil")

        return cls(
            discord_token=_req("DISCORD_TOKEN"),
            guild_id=_int("GUILD_ID"),
            model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip(),
            report_channel_id=report,
            suggestion_channel_id=_int("SUGGESTION_CHANNEL_ID"),
            ticket_category_ids=_ids("TICKET_CATEGORY_IDS"),
            ticket_prefix=os.getenv("TICKET_CHANNEL_PREFIX", "ticket-").strip().lower(),
            ticket_auto_summary_delay=_int("TICKET_AUTO_SUMMARY_DELAY", 300),
            daily_summary_time=time(hh, mm, tzinfo=tz),
            moderation_enabled=_bool("MODERATION_ENABLED", True),
            mod_log_channel_id=_int("MOD_LOG_CHANNEL_ID") or report,
            mod_ignored_channel_ids=_ids("MOD_IGNORED_CHANNEL_IDS"),
            mod_exempt_role_ids=_ids("MOD_EXEMPT_ROLE_IDS"),
            mod_batch_seconds=max(5, _int("MOD_BATCH_SECONDS", 15)),
            warn_timeout_threshold=max(1, _int("WARN_TIMEOUT_THRESHOLD", 3)),
            timeout_minutes=max(1, _int("TIMEOUT_MINUTES", 30)),
            warn_expire_days=max(1, _int("WARN_EXPIRE_DAYS", 30)),
            rules_text=rules_text,
            db_path=ROOT / "bot.db",
        )
