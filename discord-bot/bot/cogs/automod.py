from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..automod_engine import AutomodEngine, Rules, Violation, normalize
from ..util import ERR_COLOR, clip, embed, reply, require_manage_guild, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

K = "automod."
RULE_DEFAULTS: dict[str, bool] = {"invites": True, "links": False, "spam": True, "caps": False, "warn": True}
RuleName = Literal["invites", "links", "spam", "caps", "warn"]
WARNING_TTL = 8


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Automod(commands.GroupCog, group_name="automod", group_description="Otomatik moderasyon ayarları"):
    word = app_commands.Group(name="word", description="Yasaklı kelimeler")
    domain = app_commands.Group(name="domain", description="Link filtresi açıkken izin verilen siteler")

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self.engine = AutomodEngine()
        self._rules: dict[int, Rules] = {}
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage_guild(interaction)

    async def cog_load(self) -> None:
        self.prune_loop.start()

    async def cog_unload(self) -> None:
        self.prune_loop.cancel()

    @tasks.loop(minutes=5)
    async def prune_loop(self) -> None:
        self.engine.prune()

    # ---------- Kural önbelleği ----------

    def _get(self, guild_id: int, rule: str) -> bool:
        return self.bot.settings.get_bool(guild_id, K + rule, RULE_DEFAULTS[rule])

    def rules_for(self, guild_id: int) -> Rules:
        cached = self._rules.get(guild_id)
        if cached is None:
            s = self.bot.settings
            cached = Rules(
                invites=self._get(guild_id, "invites"),
                links=self._get(guild_id, "links"),
                allowed_domains=frozenset(s.get_strs(guild_id, K + "domains")),
                words=frozenset(w for w in (normalize(x) for x in s.get_strs(guild_id, K + "words")) if w),
                max_mentions=s.get_int(guild_id, K + "max_mentions", 5),
                spam=self._get(guild_id, "spam"),
                caps=self._get(guild_id, "caps"),
            )
            self._rules[guild_id] = cached
        return cached

    def _invalidate(self, guild_id: int) -> None:
        self._rules.pop(guild_id, None)

    # ---------- Mesaj kontrolü ----------

    def _exempt(self, message: discord.Message) -> bool:
        assert message.guild is not None
        s = self.bot.settings
        gid = message.guild.id
        if not s.get_bool(gid, K + "enabled"):
            return True
        author = message.author
        if not isinstance(author, discord.Member) or author.guild_permissions.manage_messages:
            return True
        if message.channel.id in s.get_ids(gid, K + "exempt_channels"):
            return True
        exempt_roles = set(s.get_ids(gid, K + "exempt_roles"))
        return any(r.id in exempt_roles for r in author.roles)

    async def _inspect(self, message: discord.Message, *, is_edit: bool = False) -> None:
        if message.guild is None or message.author.bot or not message.content or self._exempt(message):
            return
        mentions = len(set(message.raw_mentions)) + len(message.raw_role_mentions) + (10 if message.mention_everyone else 0)
        violation = self.engine.check(
            message.guild.id, message.author.id, message.content, mentions, self.rules_for(message.guild.id), is_edit=is_edit
        )
        if violation is not None:
            await self._punish(message, violation)

    async def _punish(self, message: discord.Message, violation: Violation) -> None:
        member = message.author
        assert isinstance(member, discord.Member)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        note = ""
        if self._get(member.guild.id, "warn"):
            result = await self.bot.warns.warn(member, member.guild.me, f"Automod: {violation.rule}")
            note = f" (warning {result.count})"
        try:
            await message.channel.send(
                f"⚠️ {member.mention} {violation.reason}{note}",
                delete_after=WARNING_TTL,
                allowed_mentions=discord.AllowedMentions(users=[member], everyone=False, roles=False),
            )
        except discord.HTTPException:
            pass
        e = embed(f"🛡️ Automod · {violation.rule}", clip(message.content, 1000), ERR_COLOR)
        e.add_field(name="User", value=f"{member.mention} (`{member.id}`)")
        e.add_field(name="Channel", value=f"<#{message.channel.id}>")
        await send_log(self.bot, member.guild, "modlog.channel", e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._inspect(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.content != after.content:  # düzenleyerek filtre atlatılmasın
            await self._inspect(after, is_edit=True)

    # ---------- Ayar komutları ----------

    @staticmethod
    def _mark(value: bool) -> str:
        return "✅" if value else "❌"

    @app_commands.command(name="status", description="Automod ayarlarını göster")
    async def status(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        s = self.bot.settings
        r = self.rules_for(gid)
        lines = [
            f"**Automod:** {self._mark(s.get_bool(gid, K + 'enabled'))}",
            f"Davet linki: {self._mark(r.invites)} · Link: {self._mark(r.links)} · Spam/flood: {self._mark(r.spam)} · Büyük harf: {self._mark(r.caps)}",
            f"İhlalde uyarı ver: {self._mark(self._get(gid, 'warn'))} · Maks. etiket: {r.max_mentions or 'kapalı'}",
            f"Yasaklı kelime: {len(r.words)} · İzinli site: {', '.join(sorted(r.allowed_domains)) or '—'}",
            f"Muaf kanallar: {' '.join(f'<#{c}>' for c in s.get_ids(gid, K + 'exempt_channels')) or '—'}",
            f"Muaf roller: {' '.join(f'<@&{x}>' for x in s.get_ids(gid, K + 'exempt_roles')) or '—'}",
        ]
        await interaction.response.send_message(embed=embed("🛡️ Automod", "\n".join(lines)), ephemeral=True)

    @app_commands.command(name="enable", description="Automod'u aç/kapat")
    async def enable(self, interaction: discord.Interaction, on: bool) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, K + "enabled", on)
        await reply(interaction, f"Automod {'açıldı' if on else 'kapatıldı'}.")

    @app_commands.command(name="rule", description="Tek bir kuralı aç/kapat")
    @app_commands.describe(rule="Kural", on="Açık mı?")
    async def rule(self, interaction: discord.Interaction, rule: RuleName, on: bool) -> None:
        assert interaction.guild is not None
        if rule not in RULE_DEFAULTS:
            return await reply(interaction, "Geçersiz kural.", ok=False)
        await self.bot.settings.set(interaction.guild.id, K + rule, on)
        self._invalidate(interaction.guild.id)
        await reply(interaction, f"`{rule}` {'açık' if on else 'kapalı'}.")

    @app_commands.command(name="mentions", description="Bir mesajda en fazla kaç etiket olabilir (0 = kapalı)")
    async def mentions(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 50]) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, K + "max_mentions", limit)
        self._invalidate(interaction.guild.id)
        await reply(interaction, f"Etiket limiti: {limit or 'kapalı'}.")

    @app_commands.command(name="exempt", description="Bir kanalı veya rolü automod'dan muaf tut / muafiyeti kaldır")
    async def exempt(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                     role: discord.Role | None = None) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        if channel is None and role is None:
            return await reply(interaction, "Bir kanal veya rol seç.", ok=False)
        out: list[str] = []
        for key, obj in ((K + "exempt_channels", channel), (K + "exempt_roles", role)):
            if obj is None:
                continue
            if await self.bot.settings.add_to_list(gid, key, obj.id, limit=100):
                out.append(f"{obj.mention} muaf.")
            else:
                await self.bot.settings.remove_from_list(gid, key, obj.id)
                out.append(f"{obj.mention} artık muaf değil.")
        await reply(interaction, "\n".join(out))

    @word.command(name="add", description="Yasaklı kelime ekle (virgülle birden fazla)")
    async def word_add(self, interaction: discord.Interaction, words: str) -> None:
        assert interaction.guild is not None
        added = [w for w in (x.strip().lower()[:50] for x in words.split(",")) if w
                 and await self.bot.settings.add_to_list(interaction.guild.id, K + "words", w, limit=500)]
        self._invalidate(interaction.guild.id)
        await reply(interaction, f"{len(added)} kelime eklendi." if added else "Eklenmedi (zaten var veya liste dolu).")

    @word.command(name="remove", description="Yasaklı kelimeyi kaldır")
    async def word_remove(self, interaction: discord.Interaction, word: str) -> None:
        assert interaction.guild is not None
        ok = await self.bot.settings.remove_from_list(interaction.guild.id, K + "words", word.strip().lower())
        self._invalidate(interaction.guild.id)
        await reply(interaction, "Kaldırıldı." if ok else "Listede yok.", ok=ok)

    @word.command(name="list", description="Yasaklı kelimeleri göster")
    async def word_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        words = self.bot.settings.get_strs(interaction.guild.id, K + "words")
        text = ", ".join(f"||{w}||" for w in words) if words else "Liste boş."
        await interaction.response.send_message(embed=embed("Yasaklı kelimeler", clip(text, 4000)), ephemeral=True)

    @domain.command(name="add", description="İzinli site ekle (örn. youtube.com)")
    async def domain_add(self, interaction: discord.Interaction, domain: str) -> None:
        assert interaction.guild is not None
        d = domain.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if not d or "." not in d:
            return await reply(interaction, "Geçersiz site adı.", ok=False)
        await self.bot.settings.add_to_list(interaction.guild.id, K + "domains", d, limit=100)
        self._invalidate(interaction.guild.id)
        await reply(interaction, f"`{d}` izinli.")

    @domain.command(name="remove", description="İzinli siteyi kaldır")
    async def domain_remove(self, interaction: discord.Interaction, domain: str) -> None:
        assert interaction.guild is not None
        ok = await self.bot.settings.remove_from_list(interaction.guild.id, K + "domains", domain.strip().lower())
        self._invalidate(interaction.guild.id)
        await reply(interaction, "Kaldırıldı." if ok else "Listede yok.", ok=ok)
