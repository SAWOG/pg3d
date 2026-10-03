from __future__ import annotations

from typing import Any, Callable, TypeVar

import discord
from discord import app_commands

_F = TypeVar("_F", bound=Callable[..., Any])

EMBED_DESC_LIMIT = 4096
FIELD_LIMIT = 1024


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def chunk_lines(blocks: list[str], limit: int = EMBED_DESC_LIMIT) -> list[str]:
    """Metin bloklarını embed açıklama limitini aşmayacak parçalara böler."""
    chunks: list[str] = []
    current = ""
    for block in blocks:
        block = clip(block, limit)
        if current and len(current) + len(block) + 2 > limit:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks


def serialize(message: discord.Message) -> dict[str, object]:
    """Mesajı Claude'a gönderilecek sade bir sözlüğe çevirir."""
    data: dict[str, object] = {
        "author": message.author.display_name,
        "time": message.created_at.strftime("%Y-%m-%d %H:%M"),
        "content": message.clean_content,
    }
    if isinstance(message.author, discord.Member) and message.author.guild_permissions.manage_messages:
        data["staff"] = True
    if message.attachments:
        data["attachments"] = [a.filename for a in message.attachments]
    reactions = sum(r.count for r in message.reactions)
    if reactions:
        data["reactions"] = reactions
    return data


async def collect_history(
    channel: discord.abc.Messageable,
    *,
    limit: int | None = None,
    after: discord.abc.Snowflake | None = None,
    include_bots: bool = False,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    async for msg in channel.history(limit=limit, after=after, oldest_first=True):
        if msg.author.bot and not include_bots:
            continue
        if not msg.clean_content and not msg.attachments:
            continue
        out.append(serialize(msg))
    return out


async def resolve_text_channel(client: discord.Client, channel_id: int) -> discord.TextChannel | None:
    if not channel_id:
        return None
    ch = client.get_channel(channel_id)
    if ch is None:
        try:
            ch = await client.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return None
    return ch if isinstance(ch, discord.TextChannel) else None


def staff_only() -> Callable[[_F], _F]:
    """Varsayılan izin sunucu ayarlarından değiştirilebildiği için yetki sunucu tarafında tekrar doğrulanır."""

    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.guild_permissions.manage_messages:
            raise app_commands.MissingPermissions(["manage_messages"])
        return True

    return app_commands.check(predicate)
