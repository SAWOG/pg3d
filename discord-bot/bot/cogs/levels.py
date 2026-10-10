from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..util import OK_COLOR, clip, embed, manage_guild_only, reply, role_assignable

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

K = "levels."
XP_COOLDOWN = 60.0
XP_MIN, XP_MAX = 15, 25
DEFAULT_MESSAGE = "🎉 {user} reached level **{level}**!"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS levels (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    xp       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_levels_xp ON levels (guild_id, xp DESC);
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);
"""


def xp_to_next(level: int) -> int:
    """Bir sonraki seviye için gereken XP (MEE6/Arcane ile aynı eğri)."""
    return 5 * level * level + 50 * level + 100


def level_info(total_xp: int) -> tuple[int, int, int]:
    """(seviye, bu seviyedeki xp, sonraki seviyeye gereken xp)"""
    level = 0
    while total_xp >= xp_to_next(level):
        total_xp -= xp_to_next(level)
        level += 1
    return level, total_xp, xp_to_next(level)


def progress_bar(current: int, needed: int, width: int = 14) -> str:
    filled = round(width * current / needed) if needed else width
    return "▰" * filled + "▱" * (width - filled)


class Levels(commands.Cog):
    """Arcane tarzı seviye sistemi: mesaj başına XP, seviye rolleri, sıralama."""

    levels = app_commands.Group(
        name="levels", description="Seviye sistemi ayarları", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    role = app_commands.Group(name="role", description="Seviye rolleri", parent=levels)

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._last_xp: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        self.prune_loop.start()

    async def cog_unload(self) -> None:
        self.prune_loop.cancel()

    @tasks.loop(minutes=10)
    async def prune_loop(self) -> None:
        cutoff = time.monotonic() - XP_COOLDOWN
        for key in [k for k, t in self._last_xp.items() if t < cutoff]:
            del self._last_xp[key]

    # ---------- XP kazanma ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        gid = message.guild.id
        s = self.bot.settings
        if not s.get_bool(gid, K + "enabled", True) or message.channel.id in s.get_ids(gid, K + "no_xp_channels"):
            return
        key = (gid, message.author.id)
        now = time.monotonic()
        if now - self._last_xp.get(key, 0.0) < XP_COOLDOWN:  # spam ile XP kasılmasın
            return
        self._last_xp[key] = now

        gain = random.randint(XP_MIN, XP_MAX)
        await self.bot.db.execute(
            "INSERT INTO levels (guild_id, user_id, xp) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = xp + excluded.xp",
            (gid, message.author.id, gain),
        )
        row = await self.bot.db.fetchone("SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", key)
        total = int(row[0]) if row else gain
        new_level = level_info(total)[0]
        if new_level > level_info(total - gain)[0]:
            await self._on_level_up(message, message.author, new_level)

    async def _on_level_up(self, message: discord.Message, member: discord.Member, level: int) -> None:
        gid = member.guild.id
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM level_roles WHERE guild_id = ? AND level <= ?", (gid, level)
        )
        roles = [r for (rid,) in rows if (r := member.guild.get_role(int(rid))) and r not in member.roles and role_assignable(r) is None]
        if roles:
            try:
                await member.add_roles(*roles, reason=f"Level {level}")
            except discord.HTTPException as e:
                log.warning("Seviye rolü verilemedi: %s", e)

        s = self.bot.settings
        if s.get_bool(gid, K + "announce_off"):
            return
        target = member.guild.get_channel(s.get_int(gid, K + "channel")) or message.channel
        text = s.get_str(gid, K + "message", DEFAULT_MESSAGE).replace("{user}", member.mention).replace("{level}", str(level))
        if roles:
            text += "\n" + " ".join(f"🎁 {r.mention}" for r in roles)
        if isinstance(target, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            try:
                await target.send(text[:2000], allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False))
            except discord.HTTPException:
                pass

    # ---------- Herkese açık komutlar ----------

    @app_commands.command(name="rank", description="Show your level and XP")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        assert interaction.guild is not None
        row = await self.bot.db.fetchone("SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", (interaction.guild.id, target.id))
        total = int(row[0]) if row else 0
        pos = await self.bot.db.fetchone("SELECT COUNT(*) + 1 FROM levels WHERE guild_id = ? AND xp > ?", (interaction.guild.id, total))
        level, current, needed = level_info(total)
        e = embed(f"{target.display_name}", color=OK_COLOR)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Level", value=str(level))
        e.add_field(name="Rank", value=f"#{pos[0] if pos else '?'}")
        e.add_field(name="Total XP", value=f"{total:,}")
        e.add_field(name=f"Progress · {current:,}/{needed:,} XP", value=progress_bar(current, needed), inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="Top 10 members by XP")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = await self.bot.db.fetchall(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10", (interaction.guild.id,)
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — level **{level_info(int(xp))[0]}** · {int(xp):,} XP"
                 for i, (uid, xp) in enumerate(rows)]
        await interaction.response.send_message(
            embed=embed("🏆 Level leaderboard", "\n".join(lines) or "No one has XP yet."),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ---------- Yönetici ayarları ----------

    @levels.command(name="toggle", description="Seviye sistemini aç/kapat")
    @manage_guild_only()
    async def toggle(self, interaction: discord.Interaction, on: bool) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, K + "enabled", on)
        await reply(interaction, f"Seviye sistemi {'açık' if on else 'kapalı'}.")

    @levels.command(name="channel", description="Seviye atlama mesajlarının kanalı (boş = mesajın yazıldığı kanal)")
    @manage_guild_only()
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                      announce: bool = True) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        await self.bot.settings.set(gid, K + "announce_off", not announce)
        if channel is None:
            await self.bot.settings.delete(gid, K + "channel")
        else:
            await self.bot.settings.set(gid, K + "channel", channel.id)
        where = channel.mention if channel else "mesajın yazıldığı kanal"
        await reply(interaction, f"Seviye mesajları: {where}" if announce else "Seviye atlama mesajları kapalı.")

    @levels.command(name="message", description="Seviye atlama mesajı ({user}, {level})")
    @manage_guild_only()
    async def message(self, interaction: discord.Interaction, text: str) -> None:
        assert interaction.guild is not None
        await self.bot.settings.set(interaction.guild.id, K + "message", clip(text, 500))
        await reply(interaction, "Mesaj kaydedildi.")

    @levels.command(name="noxp", description="Bir kanalda XP kazanmayı kapat/aç")
    @manage_guild_only()
    async def noxp(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        if await self.bot.settings.add_to_list(gid, K + "no_xp_channels", channel.id, limit=100):
            return await reply(interaction, f"{channel.mention} kanalında XP kazanılmayacak.")
        await self.bot.settings.remove_from_list(gid, K + "no_xp_channels", channel.id)
        await reply(interaction, f"{channel.mention} kanalında tekrar XP kazanılacak.")

    @levels.command(name="reset", description="Bir üyenin XP'sini sıfırla")
    @manage_guild_only()
    async def reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self.bot.db.execute("DELETE FROM levels WHERE guild_id = ? AND user_id = ?", (member.guild.id, member.id))
        await reply(interaction, f"{member.mention} XP'si sıfırlandı.")

    @role.command(name="add", description="Bir seviyeye ulaşınca verilecek rol")
    @manage_guild_only()
    async def role_add(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500], role: discord.Role) -> None:
        assert interaction.guild is not None
        if err := role_assignable(role):
            return await reply(interaction, err, ok=False)
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (interaction.guild.id, level, role.id)
        )
        await reply(interaction, f"Seviye {level} → {role.mention}")

    @role.command(name="remove", description="Seviye rolünü kaldır")
    @manage_guild_only()
    async def role_remove(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500]) -> None:
        assert interaction.guild is not None
        n = await self.bot.db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (interaction.guild.id, level))
        await reply(interaction, "Kaldırıldı." if n else "Bu seviyede rol yok.", ok=bool(n))

    @role.command(name="list", description="Seviye rollerini göster")
    @manage_guild_only()
    async def role_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = await self.bot.db.fetchall(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level", (interaction.guild.id,)
        )
        text = "\n".join(f"Seviye **{lv}** → <@&{rid}>" for lv, rid in rows) or "Seviye rolü yok."
        await interaction.response.send_message(embed=embed("🎁 Seviye rolleri", text), ephemeral=True)
