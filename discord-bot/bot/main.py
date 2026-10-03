from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .ai import AIClient, AIError
from .config import Config
from .storage import WarningStore

log = logging.getLogger(__name__)


class HelperBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Developer Portal'da da açılmalı
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.config = config
        self.ai = AIClient(config.model, config.rules_text)
        self.store = WarningStore(config.db_path, config.warn_expire_days)
        self.tree.error(self._on_app_command_error)

    async def setup_hook(self) -> None:
        from .cogs.moderation import Moderation
        from .cogs.suggestions import Suggestions
        from .cogs.tickets import Tickets

        tickets = Tickets(self)
        await self.add_cog(tickets)
        await self.add_cog(Suggestions(self))
        await self.add_cog(Moderation(self, tickets))

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("%d slash komutu senkronlandı", len(synced))

    async def on_ready(self) -> None:
        log.info("Giriş yapıldı: %s (%s)", self.user, getattr(self.user, "id", "?"))

    async def close(self) -> None:
        await super().close()
        await self.ai.close()
        self.store.close()

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            text = "Bu komutu kullanma yetkin yok."
        elif isinstance(original, AIError):
            text = f"AI hatası: {original}"
        elif isinstance(original, discord.Forbidden):
            text = "Botun bu işlem için yetkisi yok (kanal/rol izinlerini kontrol et)."
        else:
            log.exception("Komut hatası", exc_info=original)
            text = "Beklenmeyen bir hata oluştu."

        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
