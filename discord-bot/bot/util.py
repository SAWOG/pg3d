from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .main import HelperBot

_F = TypeVar("_F", bound=Callable[..., Any])


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())  # satır sonlarını tek satıra indir
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_staff(user: discord.abc.User, staff_role_ids: frozenset[int]) -> bool:
    if not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.manage_messages:
        return True
    return any(r.id in staff_role_ids for r in user.roles)


def staff_only() -> Callable[[_F], _F]:
    """Discord'daki komut izni sunucu ayarından değiştirilebildiği için yetki burada tekrar doğrulanır."""

    async def predicate(interaction: discord.Interaction) -> bool:
        bot: HelperBot = interaction.client  # type: ignore[assignment]
        if not is_staff(interaction.user, bot.config.staff_role_ids):
            raise app_commands.MissingPermissions(["manage_messages"])
        return True

    return app_commands.check(predicate)
