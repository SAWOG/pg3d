from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..ai import AIError, Violation
from ..util import clip, resolve_text_channel, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot
    from .tickets import Tickets

log = logging.getLogger(__name__)

MAX_BATCH = 25        # bu kadar mesaj birikince beklemeden kontrol et
MAX_BUFFER = 300      # API erişilemezse bellek şişmesin
WARNING_TTL = 120     # kanaldaki uyarı mesajı kaç saniye sonra silinsin
SEVERITY_EMOJI = {"low": "🟡", "medium": "🟠", "high": "🔴"}


class Moderation(commands.Cog):
    def __init__(self, bot: HelperBot, tickets: Tickets) -> None:
        self.bot = bot
        self.tickets = tickets
        self._buffer: deque[discord.Message] = deque(maxlen=MAX_BUFFER)
        self._flush_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self.flush_loop.change_interval(seconds=bot.config.mod_batch_seconds)

    async def cog_load(self) -> None:
        if self.bot.config.moderation_enabled:
            self.flush_loop.start()

    async def cog_unload(self) -> None:
        self.flush_loop.cancel()

    # ---------- Toplama ----------

    def _should_check(self, message: discord.Message) -> bool:
        cfg = self.bot.config
        if not cfg.moderation_enabled or message.guild is None or message.author.bot:
            return False
        if not message.content.strip():
            return False
        if message.channel.id in cfg.mod_ignored_channel_ids or self.tickets.is_ticket(message.channel):
            return False
        author = message.author
        if not isinstance(author, discord.Member):
            return False
        if author.guild_permissions.manage_messages:
            return False
        return not any(r.id in cfg.mod_exempt_role_ids for r in author.roles)

    def _enqueue(self, message: discord.Message) -> None:
        if not self._should_check(message):
            return
        self._buffer.append(message)
        if len(self._buffer) >= MAX_BATCH and not self._flush_lock.locked():
            task = asyncio.create_task(self._flush())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        self._enqueue(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.content != after.content:  # düzenleyerek kural ihlali gizlenmesin
            self._enqueue(after)

    # ---------- Kontrol ----------

    @tasks.loop(seconds=15)  # gerçek aralık MOD_BATCH_SECONDS ile ayarlanır
    async def flush_loop(self) -> None:
        await self._flush()

    @flush_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _flush(self) -> None:
        async with self._flush_lock:
            while self._buffer:
                batch = [self._buffer.popleft() for _ in range(min(MAX_BATCH, len(self._buffer)))]
                await self._check_batch(batch)

    async def _check_batch(self, batch: list[discord.Message]) -> None:
        # Model gerçek snowflake yerine kısa ID görür; dönen ID'ler sadece bu tablodan çözülür.
        by_id = {f"m{i}": msg for i, msg in enumerate(batch)}
        payload: list[dict[str, object]] = [
            {
                "id": key,
                "author": msg.author.display_name,
                "channel": getattr(msg.channel, "name", "?"),
                "content": msg.clean_content,
            }
            for key, msg in by_id.items()
        ]
        try:
            verdict = await self.bot.ai.moderate(payload)
        except AIError as e:
            log.warning("Moderasyon kontrolü başarısız: %s", e)
            return

        handled: set[str] = set()
        for violation in verdict.violations:
            msg = by_id.get(violation.message_id)
            if msg is None or violation.message_id in handled:
                continue
            handled.add(violation.message_id)
            try:
                await self._punish(msg, violation)
            except discord.HTTPException as e:
                log.warning("Ceza uygulanamadı (%s): %s", msg.author, e)

    async def _punish(self, message: discord.Message, violation: Violation) -> None:
        cfg = self.bot.config
        member = message.author
        assert isinstance(member, discord.Member) and message.guild is not None

        count = await self.bot.store.add(message.guild.id, member.id, violation.rule, violation.reason)
        actions: list[str] = [f"Uyarı {count}/{cfg.warn_timeout_threshold}"]

        if violation.severity == "high":
            try:
                await message.delete()
                actions.append("mesaj silindi")
            except discord.NotFound:
                pass

        if count >= cfg.warn_timeout_threshold and not member.is_timed_out():
            await member.timeout(
                timedelta(minutes=cfg.timeout_minutes), reason=f"{count} uyarı: {violation.rule}"
            )
            actions.append(f"{cfg.timeout_minutes} dk timeout")

        await message.channel.send(
            f"⚠️ {member.mention}, **{violation.rule}** kuralını ihlal ettin: {violation.reason} "
            f"({count}/{cfg.warn_timeout_threshold})",
            delete_after=WARNING_TTL,
            allowed_mentions=discord.AllowedMentions(users=[member], everyone=False, roles=False),
        )
        await self._log(message, violation, actions)

    async def _log(self, message: discord.Message, violation: Violation, actions: list[str]) -> None:
        channel = await resolve_text_channel(self.bot, self.bot.config.mod_log_channel_id)
        if channel is None:
            return
        embed = discord.Embed(
            title=f"{SEVERITY_EMOJI[violation.severity]} Kural ihlali: {clip(violation.rule, 200)}",
            description=clip(message.content, 1000),
            color=discord.Color.red() if violation.severity == "high" else discord.Color.orange(),
        )
        embed.add_field(name="Kullanıcı", value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Kanal", value=f"<#{message.channel.id}>")
        embed.add_field(name="Sebep", value=clip(violation.reason, 1024), inline=False)
        embed.add_field(name="İşlem", value=", ".join(actions), inline=False)
        embed.add_field(name="Mesaj", value=f"[Git]({message.jump_url})", inline=False)
        await channel.send(embed=embed)

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
