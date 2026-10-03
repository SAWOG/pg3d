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
    """Seçili kanallarda korunan kişileri (@sawog vb.) etiketleyenleri uyarır."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        cfg = bot.config
        names = sorted(cfg.mention_guard_names, key=len, reverse=True)
        # Gerçek etiket olmasa da düz yazılmış "@sawog" metnini yakalar
        self._text_re = re.compile(r"@(?:" + "|".join(map(re.escape, names)) + r")\b", re.I) if names else None
        self._last_warned: dict[int, float] = {}

    async def cog_load(self) -> None:
        self.prune_loop.start()

    async def cog_unload(self) -> None:
        self.prune_loop.cancel()

    @tasks.loop(minutes=10)
    async def prune_loop(self) -> None:
        cutoff = time.monotonic() - self.bot.config.mention_guard_cooldown
        for uid in [u for u, t in self._last_warned.items() if t < cutoff]:
            del self._last_warned[uid]

    def _is_protected(self, user: discord.abc.User) -> bool:
        cfg = self.bot.config
        if user.id in cfg.mention_guard_user_ids:
            return True
        names = cfg.mention_guard_names
        return user.name.lower() in names or user.display_name.lower() in names

    def _targets_protected(self, message: discord.Message) -> bool:
        if any(self._is_protected(u) for u in message.mentions):
            return True
        return self._text_re is not None and self._text_re.search(message.content) is not None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        cfg = self.bot.config
        if message.guild is None or message.author.bot or not cfg.mention_guard_channel_ids:
            return
        if message.channel.id not in cfg.mention_guard_channel_ids:
            return
        if is_staff(message.author) or self._is_protected(message.author):
            return
        if not self._targets_protected(message):
            return

        now = time.monotonic()
        if now - self._last_warned.get(message.author.id, 0.0) < cfg.mention_guard_cooldown:
            return
        self._last_warned[message.author.id] = now

        text = cfg.mention_guard_message.replace("{user}", message.author.mention)
        mentions = discord.AllowedMentions(users=[message.author], everyone=False, roles=False)
        try:
            if cfg.mention_guard_delete_after:
                await message.reply(text, delete_after=cfg.mention_guard_delete_after, allowed_mentions=mentions)
            else:
                await message.reply(text, allowed_mentions=mentions)
        except discord.HTTPException:
            pass
