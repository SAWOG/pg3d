from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from ..util import is_staff

if TYPE_CHECKING:
    from ..main import HelperBot


class MentionGuard(commands.Cog):
    """Seçili kanallarda @sawog / @admin etiketleyenlere ticket açmalarını söyler."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        names = sorted(bot.config.guard_target_names, key=len, reverse=True)
        # Gerçek etiket olmayan, düz yazılmış "@sawog" / "@admin" metnini de yakalar
        self._text_re = re.compile(r"@(?:" + "|".join(map(re.escape, names)) + r")\b", re.I) if names else None
        self._last_warned: dict[int, float] = {}

    async def cog_load(self) -> None:
        if self.bot.config.guard_cooldown:
            self.prune_loop.start()

    async def cog_unload(self) -> None:
        self.prune_loop.cancel()

    @tasks.loop(minutes=10)
    async def prune_loop(self) -> None:
        cutoff = time.monotonic() - self.bot.config.guard_cooldown
        for uid in [u for u, t in self._last_warned.items() if t < cutoff]:
            del self._last_warned[uid]

    def _channel_enabled(self, channel: discord.abc.Messageable) -> bool:
        cfg = self.bot.config
        ch_id = getattr(channel, "id", 0)
        name = str(getattr(channel, "name", "")).lower()
        return ch_id in cfg.guard_channel_ids or name in cfg.guard_channel_names

    def _is_target(self, obj: discord.abc.User | discord.Role) -> bool:
        cfg = self.bot.config
        if obj.id in cfg.guard_target_ids:
            return True
        names = {obj.name.lower()}
        if isinstance(obj, (discord.User, discord.Member)):
            names.add(obj.display_name.lower())
            if obj.global_name:
                names.add(obj.global_name.lower())
        return not names.isdisjoint(cfg.guard_target_names)

    def _mentions_target(self, message: discord.Message) -> bool:
        # raw_mentions sadece mesaj metnindeki etiketleri içerir; "yanıtla" ile gelen otomatik ping sayılmaz
        explicit = set(message.raw_mentions)
        if any(u.id in explicit and self._is_target(u) for u in message.mentions):
            return True
        if any(self._is_target(r) for r in message.role_mentions):
            return True
        return self._text_re is not None and self._text_re.search(message.content) is not None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not self._channel_enabled(message.channel):
            return
        if is_staff(message.author, self.bot.config.staff_role_ids) or self._is_target(message.author):
            return
        if not self._mentions_target(message):
            return

        cooldown = self.bot.config.guard_cooldown
        if cooldown:
            now = time.monotonic()
            if now - self._last_warned.get(message.author.id, 0.0) < cooldown:
                return
            self._last_warned[message.author.id] = now

        try:
            await message.reply(
                self.bot.config.guard_message,
                mention_author=True,
                allowed_mentions=discord.AllowedMentions(users=[message.author], everyone=False, roles=False),
            )
        except discord.HTTPException:
            pass
