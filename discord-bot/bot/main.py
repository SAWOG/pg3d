from __future__ import annotations

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .config import Config
from .db import Database
from .settings import Settings
from .translate import Translator
from .util import reply
from .warns import WarningService

log = logging.getLogger(__name__)


class HelperBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Developer Portal'da açılmalı
        intents.members = True          # Developer Portal'da açılmalı (hoş geldin, davet takibi, loglar)
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            help_command=None,
        )
        self.config = config
        self.db = Database(config.db_path)
        self.settings = Settings(self.db)
        self.translator = Translator(config.translate_enabled)
        self.warns = WarningService(self)
        self._http: aiohttp.ClientSession | None = None
        self.tree.error(self._on_app_command_error)

    @property
    def http_session(self) -> aiohttp.ClientSession:
        """Dış servisler (YouTube RSS, nekos.best) için paylaşılan oturum."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15), headers={"User-Agent": "Mozilla/5.0 (DiscordBot)"}
            )
        return self._http

    async def setup_hook(self) -> None:
        await self.settings.load()
        await self.warns.init()

        from .cogs import ALL_COGS

        for cog_cls in ALL_COGS:
            await self.add_cog(cog_cls(self))

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("%d slash komutu senkronlandı", len(synced))

    async def on_ready(self) -> None:
        log.info("Giriş yapıldı: %s (%s) · %d sunucu", self.user, getattr(self.user, "id", "?"), len(self.guilds))

    async def close(self) -> None:
        await super().close()
        await self.translator.close()
        if self._http is not None:
            await self._http.close()
        self.db.close()

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.CommandOnCooldown):
            text = f"Slow down! Try again in {error.retry_after:.0f}s."
        elif isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            text = "You don't have permission to use this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            text = f"I'm missing permissions: {', '.join(error.missing_permissions)}"
        elif isinstance(original, discord.Forbidden):
            text = "I don't have permission to do that (check my role position and channel permissions)."
        else:
            log.exception("Komut hatası (%s)", interaction.command and interaction.command.qualified_name, exc_info=original)
            text = "Something went wrong."
        try:
            await reply(interaction, text, ok=False)
        except discord.HTTPException:
            pass
