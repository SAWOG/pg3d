from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..filters import RuleFilter, Violation
from ..util import clip, is_staff, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot
    from .tickets import Tickets

log = logging.getLogger(__name__)

WARNING_TTL = 30  # kanaldaki uyarı mesajı kaç saniye sonra silinsin
SEVERITY_EMOJI = {"low": "🟡", "medium": "🟠", "high": "🔴"}


class Moderation(commands.Cog):
    def __init__(self, bot: HelperBot, tickets: Tickets) -> None:
        self.bot = bot
        self.tickets = tickets
        self.filter = RuleFilter(bot.config)

    async def cog_load(self) -> None:
        self.prune_loop.start()

    async def cog_unload(self) -> None:
        self.prune_loop.cancel()

    @tasks.loop(minutes=5)
    async def prune_loop(self) -> None:
        self.filter.prune()  # pasif kullanıcıların spam sayaçlarını bellekten at

    def _should_check(self, message: discord.Message) -> bool:
        cfg = self.bot.config
        if not cfg.moderation_enabled or message.guild is None or message.author.bot:
            return False
        if message.channel.id in cfg.mod_ignored_channel_ids or self.tickets.is_ticket(message.channel):
            return False
        author = message.author
        if not isinstance(author, discord.Member) or is_staff(author):
            return False
        return not any(r.id in cfg.mod_exempt_role_ids for r in author.roles)

    async def _inspect(self, message: discord.Message, *, is_edit: bool = False) -> None:
        if not self._should_check(message):
            return
        mentions = len(set(message.raw_mentions)) + len(message.raw_role_mentions) + (10 if message.mention_everyone else 0)
        violation = self.filter.check(message.author.id, message.content, mentions, is_edit=is_edit)
        if violation is None:
            return
        try:
            await self._punish(message, violation)
        except discord.HTTPException as e:
            log.warning("Ceza uygulanamadı (%s): %s", message.author, e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._inspect(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.content != after.content:  # düzenleyerek filtre atlatılmasın
            await self._inspect(after, is_edit=True)

    async def _punish(self, message: discord.Message, violation: Violation) -> None:
        cfg = self.bot.config
        member = message.author
        assert isinstance(member, discord.Member) and message.guild is not None

        count = await self.bot.store.add(message.guild.id, member.id, violation.rule, violation.reason)
        actions: list[str] = [f"Uyarı {count}/{cfg.warn_timeout_threshold}"]

        if violation.delete:
            try:
                await message.delete()
                actions.append("mesaj silindi")
            except discord.NotFound:
                pass

        if count >= cfg.warn_timeout_threshold and not member.is_timed_out():
            await member.timeout(timedelta(minutes=cfg.timeout_minutes), reason=f"{count} uyarı: {violation.rule}")
            actions.append(f"{cfg.timeout_minutes} dk timeout")

        await message.channel.send(
            f"⚠️ {member.mention}, **{violation.rule}**: {violation.reason} ({count}/{cfg.warn_timeout_threshold})",
            delete_after=WARNING_TTL,
            allowed_mentions=discord.AllowedMentions(users=[member], everyone=False, roles=False),
        )
        await self._log(message, violation, actions)

    async def _log(self, message: discord.Message, violation: Violation, actions: list[str]) -> None:
        channel = await resolve_text_channel(self.bot, self.bot.config.mod_log_channel_id)
        if channel is None:
            return
        embed = discord.Embed(
            title=f"{SEVERITY_EMOJI[violation.severity]} {violation.rule}",
            description=clip(message.content, 1000) or "*(boş)*",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Kullanıcı", value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Kanal", value=f"<#{message.channel.id}>")
        embed.add_field(name="İşlem", value=", ".join(actions), inline=False)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # ---------- Komutlar ----------

    @app_commands.command(name="uyarilar", description="Bir üyenin aktif uyarılarını gösterir")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @staff_only()
    async def warnings(self, interaction: discord.Interaction, uye: discord.Member) -> None:
        assert interaction.guild is not None
        rows = await self.bot.store.list(interaction.guild.id, uye.id)
        if not rows:
            await interaction.response.send_message(f"{uye.mention} için aktif uyarı yok.", ephemeral=True)
            return
        lines = [f"<t:{ts}:R> **{clip(rule, 80)}** — {clip(reason, 150)}" for rule, reason, ts in rows]
        embed = discord.Embed(
            title=f"{uye.display_name} · {len(rows)} uyarı",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="uyari-sil", description="Bir üyenin tüm uyarılarını siler")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @staff_only()
    async def clear_warnings(self, interaction: discord.Interaction, uye: discord.Member) -> None:
        assert interaction.guild is not None
        await self.bot.store.clear(interaction.guild.id, uye.id)
        await interaction.response.send_message(f"{uye.mention} uyarıları silindi.", ephemeral=True)
