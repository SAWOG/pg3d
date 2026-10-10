from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..util import ERR_COLOR, OK_COLOR, embed, reply, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

VANITY = "vanity"
FAKE_ACCOUNT_DAYS = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_joins (
    guild_id   INTEGER NOT NULL,
    member_id  INTEGER NOT NULL,
    inviter_id INTEGER,
    code       TEXT,
    joined_at  INTEGER NOT NULL,
    left_at    INTEGER,
    fake       INTEGER NOT NULL DEFAULT 0,
    rejoins    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_invite_inviter ON invite_joins (guild_id, inviter_id);
"""


class InviteStats:
    __slots__ = ("total", "left", "fake")

    def __init__(self, total: int, left: int, fake: int) -> None:
        self.total, self.left, self.fake = total, left, fake

    @property
    def real(self) -> int:
        return max(0, self.total - self.left - self.fake)


class Invites(commands.GroupCog, group_name="invites", group_description="Invite tracking"):
    """Invite Tracker / InviteLogger: kim kimi davet etti, ayrılanlar, sahte hesaplar, tekrar girenler."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._cache: dict[int, dict[str, tuple[int, int | None]]] = {}  # guild -> code -> (uses, inviter_id)
        self._locks: dict[int, asyncio.Lock] = {}
        super().__init__()

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        if self.bot.is_ready():
            for guild in self.bot.guilds:
                await self._snapshot(guild)

    async def _fetch(self, guild: discord.Guild) -> dict[str, tuple[int, int | None]] | None:
        if not guild.me.guild_permissions.manage_guild:
            return None  # davetleri okumak için "Sunucuyu Yönet" izni gerekir
        try:
            invites = await guild.invites()
        except discord.HTTPException:
            return None
        data = {i.code: (i.uses or 0, i.inviter.id if i.inviter else None) for i in invites}
        if "VANITY_URL" in guild.features:
            try:
                vanity = await guild.vanity_invite()
                if vanity is not None:
                    data[VANITY] = (vanity.uses or 0, None)
            except discord.HTTPException:
                pass
        return data

    async def _snapshot(self, guild: discord.Guild) -> None:
        data = await self._fetch(guild)
        if data is not None:
            self._cache[guild.id] = data

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            await self._snapshot(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._snapshot(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if isinstance(invite.guild, discord.Guild):
            self._cache.setdefault(invite.guild.id, {})[invite.code] = (invite.uses or 0, invite.inviter.id if invite.inviter else None)

    # on_invite_delete bilinçli olarak dinlenmiyor: tek kullanımlık davetler, üye katıldığı anda silinir;
    # eski kayıt önbellekte kalırsa "kaybolan davet" olarak doğru kişiye atanabilir.

    @staticmethod
    def find_used(old: dict[str, tuple[int, int | None]], new: dict[str, tuple[int, int | None]]) -> tuple[str, int | None] | None:
        increased = [(code, inv) for code, (uses, inv) in new.items() if uses > old.get(code, (0, None))[0]]
        if len(increased) == 1:
            return increased[0]
        if not increased:
            vanished = [(code, old[code][1]) for code in old.keys() - new.keys() if code != VANITY]
            if len(vanished) == 1:
                return vanished[0]
        return None

    async def stats(self, guild_id: int, inviter_id: int) -> InviteStats:
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*), COALESCE(SUM(left_at IS NOT NULL), 0), COALESCE(SUM(fake = 1 AND left_at IS NULL), 0) "
            "FROM invite_joins WHERE guild_id = ? AND inviter_id = ?",
            (guild_id, inviter_id),
        )
        return InviteStats(*(int(x) for x in row)) if row else InviteStats(0, 0, 0)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        guild = member.guild
        async with self._locks.setdefault(guild.id, asyncio.Lock()):  # aynı anda katılanlar karışmasın
            old = self._cache.get(guild.id, {})
            new = await self._fetch(guild)
            if new is not None:
                self._cache[guild.id] = new
        used = self.find_used(old, new) if new is not None else None
        code, inviter_id = used if used else (None, None)
        now = int(time.time())
        fake = int((datetime.now(timezone.utc) - member.created_at).days < FAKE_ACCOUNT_DAYS)

        existing = await self.bot.db.fetchone(
            "SELECT inviter_id FROM invite_joins WHERE guild_id = ? AND member_id = ?", (guild.id, member.id)
        )
        rejoin = existing is not None
        if rejoin:
            # Anti re-join: tekrar giren kişi ilk davet edene yazılı kalır, ikinci kez sayılmaz
            inviter_id = int(existing[0]) if existing and existing[0] is not None else inviter_id
            await self.bot.db.execute(
                "UPDATE invite_joins SET left_at = NULL, rejoins = rejoins + 1 WHERE guild_id = ? AND member_id = ?",
                (guild.id, member.id),
            )
        else:
            await self.bot.db.execute(
                "INSERT INTO invite_joins (guild_id, member_id, inviter_id, code, joined_at, fake) VALUES (?, ?, ?, ?, ?, ?)",
                (guild.id, member.id, inviter_id, code, now, fake),
            )

        if code == VANITY:
            how = "using the vanity URL"
        elif inviter_id:
            st = await self.stats(guild.id, inviter_id)
            how = f"invited by <@{inviter_id}> (**{st.real}** invites)"
        else:
            how = "— I couldn't tell which invite was used"
        flags = (" · 🔁 rejoin (not counted again)" if rejoin else "") + (" · ⚠️ new account" if fake else "")
        await send_log(self.bot, guild, "invites.channel", embed(description=f"📥 {member.mention} joined {how}{flags}", color=OK_COLOR))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        row = await self.bot.db.fetchone(
            "SELECT inviter_id FROM invite_joins WHERE guild_id = ? AND member_id = ?", (member.guild.id, member.id)
        )
        await self.bot.db.execute(
            "UPDATE invite_joins SET left_at = ? WHERE guild_id = ? AND member_id = ?",
            (int(time.time()), member.guild.id, member.id),
        )
        inviter = f" (invited by <@{row[0]}>)" if row and row[0] else ""
        await send_log(self.bot, member.guild, "invites.channel", embed(description=f"📤 **{member}** left{inviter}", color=ERR_COLOR))

    # ---------- Komutlar ----------

    @app_commands.command(name="check", description="How many people someone invited")
    @app_commands.guild_only()
    async def check(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        assert interaction.guild is not None
        st = await self.stats(interaction.guild.id, target.id)
        e = embed(f"📨 {target.display_name}'s invites", f"**{st.real}** invites")
        e.add_field(name="Joined", value=str(st.total))
        e.add_field(name="Left", value=str(st.left))
        e.add_field(name="Fake (new accounts)", value=str(st.fake))
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="top", description="Invite leaderboard")
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = await self.bot.db.fetchall(
            "SELECT inviter_id, COUNT(*) - SUM(left_at IS NOT NULL) - SUM(fake = 1 AND left_at IS NULL) AS real "
            "FROM invite_joins WHERE guild_id = ? AND inviter_id IS NOT NULL GROUP BY inviter_id ORDER BY real DESC LIMIT 10",
            (interaction.guild.id,),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — **{max(0, int(n))}**" for i, (uid, n) in enumerate(rows)]
        await interaction.response.send_message(embed=embed("🏆 Invite leaderboard", "\n".join(lines) or "No data yet."))

    @app_commands.command(name="who", description="Who invited this member")
    @app_commands.guild_only()
    async def who(self, interaction: discord.Interaction, member: discord.Member) -> None:
        row = await self.bot.db.fetchone(
            "SELECT inviter_id, code FROM invite_joins WHERE guild_id = ? AND member_id = ?", (member.guild.id, member.id)
        )
        if row is None:
            text = f"I don't know who invited {member.mention} (they joined before I was tracking)."
        elif row[1] == VANITY:
            text = f"{member.mention} joined using the vanity URL."
        elif row[0]:
            text = f"{member.mention} was invited by <@{row[0]}> (code `{row[1]}`)."
        else:
            text = f"I couldn't tell who invited {member.mention}."
        await interaction.response.send_message(embed=embed(description=text), allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="channel", description="Davet log kanalı (Yönetici). Boş = kapat")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        assert interaction.guild is not None
        if channel is None:
            await self.bot.settings.delete(interaction.guild.id, "invites.channel")
            return await reply(interaction, "Davet logları kapatıldı.")
        await self.bot.settings.set(interaction.guild.id, "invites.channel", channel.id)
        warn = "" if interaction.guild.me.guild_permissions.manage_guild else "\n⚠️ Davetleri görebilmem için **Sunucuyu Yönet** iznim olmalı."
        await reply(interaction, f"Davet logları: {channel.mention}{warn}")
