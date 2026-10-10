from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .main import HelperBot

log = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

OK_COLOR = discord.Color.green()
ERR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blurple()
NO_MENTIONS = discord.AllowedMentions.none()


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())  # satır sonlarını tek satıra indir
    return text if len(text) <= limit else text[: limit - 1] + "…"


def get_bot(interaction: discord.Interaction) -> HelperBot:
    return interaction.client  # type: ignore[return-value]


def is_staff(user: discord.abc.User, staff_role_ids: frozenset[int]) -> bool:
    if not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.manage_messages:
        return True
    return any(r.id in staff_role_ids for r in user.roles)


def staff_only() -> Callable[[_F], _F]:
    """Discord'daki komut izni sunucu ayarından değiştirilebildiği için yetki burada tekrar doğrulanır."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_staff(interaction.user, get_bot(interaction).config.staff_role_ids):
            raise app_commands.MissingPermissions(["manage_messages"])
        return True

    return app_commands.check(predicate)


async def require_manage_guild(interaction: discord.Interaction) -> bool:
    """Yönetim komutları için: yetki bilgisi Discord'un gönderdiği interaction.permissions'tan gelir."""
    if not interaction.permissions.manage_guild:
        raise app_commands.MissingPermissions(["manage_guild"])
    return True


def manage_guild_only() -> Callable[[_F], _F]:
    """Alt komutlar için: Discord'un default_permissions'ı alt komutlarda çalışmadığından kontrol burada yapılır."""
    return app_commands.check(require_manage_guild)


def hierarchy_error(actor: discord.Member, target: discord.Member) -> str | None:
    """Rol hiyerarşisi kontrolü: kimse kendinden üstteki/eşit birini, bot da kendinden üsttekini cezalandıramaz."""
    guild = actor.guild
    if target.id == actor.id:
        return "You can't do this to yourself."
    if target.id == guild.owner_id:
        return "You can't moderate the server owner."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "That member's role is higher than or equal to yours."
    if target.top_role >= guild.me.top_role:
        return "That member's role is higher than or equal to mine."
    return None


def role_assignable(role: discord.Role) -> str | None:
    """Botun verebileceği bir rol mü?"""
    if role.is_default() or role.managed:
        return "Bu rol verilemez (@everyone veya bot/entegrasyon rolü)."
    if role >= role.guild.me.top_role:
        return "Bu rol botun rolünden yüksek; sunucu ayarlarında botun rolünü yukarı taşı."
    if role.permissions.administrator or role.permissions.manage_guild:
        return "Güvenlik için yönetici yetkili roller panelden/otomatik verilemez."
    return None


async def send_log(bot: HelperBot, guild: discord.Guild, key: str, embed: discord.Embed, file: discord.File | None = None) -> None:
    """Ayarlı log kanalına gönderir; kanal yoksa veya izin yoksa sessizce geçer."""
    channel = guild.get_channel(bot.settings.get_int(guild.id, key))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        if file is not None:
            await channel.send(embed=embed, file=file, allowed_mentions=NO_MENTIONS)
        else:
            await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
    except discord.HTTPException as e:
        log.warning("Log gönderilemedi (%s/%s): %s", guild.id, key, e)


def embed(title: str | None = None, description: str | None = None, color: discord.Color = INFO_COLOR) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


async def reply(interaction: discord.Interaction, text: str, *, ok: bool = True, ephemeral: bool = True) -> None:
    """Etkileşime durumuna göre (ilk cevap / followup) kısa bir embed ile cevap verir."""
    e = embed(description=text, color=OK_COLOR if ok else ERR_COLOR)
    if interaction.response.is_done():
        await interaction.followup.send(embed=e, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=e, ephemeral=ephemeral)
