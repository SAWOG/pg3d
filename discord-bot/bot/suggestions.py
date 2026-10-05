from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import discord

from .config import Config
from .storage import DecisionStore, Status
from .translate import Translator
from .util import clip

log = logging.getLogger(__name__)

SortOrder = Literal["votes", "newest", "oldest"]
DecisionResult = Literal["ok", "taken", "deleted", "failed"]
SUMMARY_CHARS = 180


@dataclass(slots=True)
class Suggestion:
    message_id: int
    author: str
    text: str
    url: str
    up: int
    down: int
    created_at: datetime
    summary: str | None = None  # Türkçe kısa özet; sadece ekranda gösterilirken doldurulur
    lang: str = "?"

    @property
    def score(self) -> int:
        return self.up - self.down


def _extract(message: discord.Message) -> tuple[str, str]:
    """(yazar, metin). Öneri botlarının embed'li mesajları da desteklenir."""
    if message.clean_content.strip():
        return message.author.display_name, message.clean_content
    for embed in message.embeds:
        text = " — ".join(p for p in (embed.title, embed.description) if p)
        if text:
            author = embed.author.name if embed.author and embed.author.name else message.author.display_name
            return author, text
    return message.author.display_name, ""


def _votes(message: discord.Message, cfg: Config) -> tuple[int, int, bool]:
    """(evet, hayır, bot_zaten_karar_verdi). Botun kendi tepkileri oy sayılmaz."""
    up = down = 0
    decided = False
    for r in message.reactions:
        emoji = str(r.emoji)
        if r.me and emoji in (cfg.accept_emoji, cfg.reject_emoji):
            decided = True
        n = r.count - (1 if r.me else 0)
        if emoji in cfg.up_emojis:
            up += n
        elif emoji in cfg.down_emojis:
            down += n
    return up, down, decided


async def collect_pending(
    channel: discord.TextChannel,
    store: DecisionStore,
    cfg: Config,
    *,
    min_votes: int,
    sort: SortOrder,
) -> list[Suggestion]:
    """Kabul/red edilmemiş önerileri toplar."""
    decided_ids = await store.decided_ids(channel.id)
    me = channel.guild.me.id
    out: list[Suggestion] = []
    async for msg in channel.history(limit=cfg.scan_limit):
        if msg.author.id == me or msg.id in decided_ids:
            continue
        # Önerilere yazılan yanıtlar / sistem mesajları öneri değildir
        if msg.type is not discord.MessageType.default or msg.reference is not None:
            continue
        author, text = _extract(msg)
        if not text.strip():
            continue
        up, down, decided = _votes(msg, cfg)
        if decided or up + down < min_votes:
            continue
        out.append(Suggestion(msg.id, author, text, msg.jump_url, up, down, msg.created_at))

    if sort == "votes":
        out.sort(key=lambda s: (s.score, s.up), reverse=True)
    elif sort == "oldest":
        out.reverse()
    return out


async def fill_summaries(items: list[Suggestion], translator: Translator) -> None:
    """Sadece özeti olmayanları çevirir (sayfa değişince tekrar istek atılmaz)."""
    todo = [s for s in items if s.summary is None]
    if not todo:
        return
    results = await translator.translate_many([s.text for s in todo])
    for s, (text, lang) in zip(todo, results):
        s.summary = clip(text, SUMMARY_CHARS)
        s.lang = lang


def decision_embed(cfg: Config, status: Status, reason: str, moderator: discord.abc.User) -> discord.Embed:
    accepted = status == "accepted"
    embed = discord.Embed(
        title=cfg.accept_title if accepted else cfg.reject_title,
        color=discord.Color.green() if accepted else discord.Color.red(),
    )
    if reason:
        embed.add_field(name=cfg.reason_label, value=reason, inline=False)
    embed.set_footer(text=f"{cfg.reviewed_by_label} {moderator.display_name}")
    return embed


async def apply_decision(
    channel: discord.TextChannel,
    store: DecisionStore,
    cfg: Config,
    suggestion: Suggestion,
    status: Status,
    reason: str,
    moderator: discord.abc.User,
) -> DecisionResult:
    """Kararı kaydeder, öneriye cevap verir ve işaret tepkisi ekler."""
    if not await store.claim(channel.guild.id, channel.id, suggestion.message_id, status, reason, moderator.id):
        return "taken"  # başka bir yetkili aynı anda karar verdi
    if status == "dismissed":
        return "ok"

    target = channel.get_partial_message(suggestion.message_id)
    try:
        await target.reply(
            embed=decision_embed(cfg, status, reason, moderator),
            mention_author=True,
            allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
        )
    except discord.NotFound:
        return "deleted"  # öneri silinmiş; tekrar listelenmesin diye kayıt kalır
    except discord.HTTPException as e:
        await store.release(suggestion.message_id)
        log.warning("Öneriye cevap gönderilemedi (%s): %s", suggestion.message_id, e)
        return "failed"

    try:
        await target.add_reaction(cfg.accept_emoji if status == "accepted" else cfg.reject_emoji)
    except discord.HTTPException:
        pass  # işaret tepkisi opsiyonel; karar zaten veritabanında
    return "ok"
