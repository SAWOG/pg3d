from __future__ import annotations

import random
import sqlite3
import time
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands

from ..util import ERR_COLOR, OK_COLOR, embed, reply

if TYPE_CHECKING:
    from ..main import HelperBot

COIN = "🪙"
DAILY_AMOUNT = 500
DAILY_COOLDOWN = 86400
WORK_RANGE = (100, 300)
WORK_COOLDOWN = 3600
MAX_BET = 1_000_000
SLOT_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "⭐", "💎")
SLOT_WEIGHTS = (30, 25, 20, 13, 8, 4)
JOBS = ("delivered pizzas", "fixed a server", "streamed for 2 hours", "walked some dogs", "mined in a cave", "sold lemonade")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS economy (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    balance    INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    last_daily INTEGER NOT NULL DEFAULT 0,
    last_work  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_economy_balance ON economy (guild_id, balance DESC);
"""


class InsufficientFunds(Exception):
    pass


def _ensure(conn: sqlite3.Connection, guild_id: int, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))


def _take(conn: sqlite3.Connection, guild_id: int, user_id: int, amount: int) -> None:
    """Bakiye yetmiyorsa InsufficientFunds fırlatır; transaction tümüyle geri alınır."""
    _ensure(conn, guild_id, user_id)
    cur = conn.execute(
        "UPDATE economy SET balance = balance - ? WHERE guild_id = ? AND user_id = ? AND balance >= ?",
        (amount, guild_id, user_id, amount),
    )
    if cur.rowcount != 1:
        raise InsufficientFunds


def _add(conn: sqlite3.Connection, guild_id: int, user_id: int, amount: int) -> int:
    _ensure(conn, guild_id, user_id)
    conn.execute("UPDATE economy SET balance = balance + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, user_id))
    row = conn.execute("SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
    return int(row[0])


def slot_payout(reels: tuple[str, str, str], bet: int) -> int:
    """Toplam geri ödeme (bahis dahil). 0 = kayıp."""
    a, b, c = reels
    if a == b == c:
        return bet * (20 if a == "💎" else 8)
    if a == b or b == c or a == c:
        return bet  # ikili: bahis iadesi (2x ödemek beklenen değeri >1 yapıp sınırsız para üretirdi)
    return 0


class Economy(commands.Cog):
    """OwO / Nekotina tarzı sunucu içi ekonomi. Tüm bakiye değişiklikleri atomik transaction'larla yapılır."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)

    async def _balance(self, guild_id: int, user_id: int) -> int:
        row = await self.bot.db.fetchone("SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return int(row[0]) if row else 0

    async def _claim(self, interaction: discord.Interaction, column: Literal["last_daily", "last_work"], cooldown: int, amount: int) -> int | None:
        """Süresi dolduysa ödülü verir ve yeni bakiyeyi döndürür; dolmadıysa None + kalan süre mesajı."""
        assert interaction.guild is not None
        gid, uid, now = interaction.guild.id, interaction.user.id, int(time.time())

        def work(conn: sqlite3.Connection) -> int | None:
            _ensure(conn, gid, uid)
            cur = conn.execute(
                f"UPDATE economy SET balance = balance + ?, {column} = ? WHERE guild_id = ? AND user_id = ? AND {column} <= ?",
                (amount, now, gid, uid, now - cooldown),
            )
            if cur.rowcount != 1:
                return None
            return int(conn.execute("SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (gid, uid)).fetchone()[0])

        balance = await self.bot.db.atomic(work)
        if balance is None:
            row = await self.bot.db.fetchone(f"SELECT {column} FROM economy WHERE guild_id = ? AND user_id = ?", (gid, uid))
            ready_at = (int(row[0]) if row else 0) + cooldown
            await reply(interaction, f"⏳ Come back <t:{ready_at}:R>.", ok=False)
        return balance

    @app_commands.command(name="balance", description="Check your coins")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        assert interaction.guild is not None
        bal = await self._balance(interaction.guild.id, target.id)
        await interaction.response.send_message(embed=embed(description=f"{COIN} **{target.display_name}** has **{bal:,}** coins."))

    @app_commands.command(name="daily", description=f"Claim {DAILY_AMOUNT} coins every 24 hours")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        bal = await self._claim(interaction, "last_daily", DAILY_COOLDOWN, DAILY_AMOUNT)
        if bal is not None:
            await reply(interaction, f"{COIN} You claimed **{DAILY_AMOUNT}** coins! Balance: **{bal:,}**", ephemeral=False)

    @app_commands.command(name="work", description="Work for coins (every hour)")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction) -> None:
        amount = random.randint(*WORK_RANGE)
        bal = await self._claim(interaction, "last_work", WORK_COOLDOWN, amount)
        if bal is not None:
            await reply(interaction, f"💼 You {random.choice(JOBS)} and earned **{amount}** coins! Balance: **{bal:,}**", ephemeral=False)

    @app_commands.command(name="give", description="Give coins to someone")
    @app_commands.guild_only()
    async def give(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, MAX_BET]) -> None:
        assert interaction.guild is not None
        if user.bot or user.id == interaction.user.id:
            return await reply(interaction, "You can't give coins to yourself or a bot.", ok=False)
        gid, sender = interaction.guild.id, interaction.user.id

        def work(conn: sqlite3.Connection) -> int:
            _take(conn, gid, sender, amount)
            return _add(conn, gid, user.id, amount)

        try:
            await self.bot.db.atomic(work)
        except InsufficientFunds:
            return await reply(interaction, "You don't have enough coins.", ok=False)
        await reply(interaction, f"{COIN} {interaction.user.mention} gave **{amount:,}** coins to {user.mention}.", ephemeral=False)

    async def _gamble(self, interaction: discord.Interaction, bet: int, payout: int) -> int | None:
        """Bahsi düşer, kazancı ekler; tek transaction. Yetersiz bakiyede None."""
        assert interaction.guild is not None
        gid, uid = interaction.guild.id, interaction.user.id

        def work(conn: sqlite3.Connection) -> int:
            _take(conn, gid, uid, bet)
            return _add(conn, gid, uid, payout)

        try:
            return await self.bot.db.atomic(work)
        except InsufficientFunds:
            await reply(interaction, "You don't have enough coins.", ok=False)
            return None

    @app_commands.command(name="coinflip", description="Bet coins on heads or tails")
    @app_commands.guild_only()
    async def coinflip(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, MAX_BET],
                       side: Literal["heads", "tails"]) -> None:
        result = random.choice(("heads", "tails"))  # sonuç sunucuda belirlenir
        won = result == side
        bal = await self._gamble(interaction, bet, bet * 2 if won else 0)
        if bal is None:
            return
        text = f"🪙 It's **{result}**! " + (f"You won **{bet:,}** coins!" if won else f"You lost **{bet:,}** coins.")
        await interaction.response.send_message(embed=embed(description=f"{text}\nBalance: **{bal:,}**", color=OK_COLOR if won else ERR_COLOR))

    @app_commands.command(name="slots", description="Spin the slot machine")
    @app_commands.guild_only()
    async def slots(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, MAX_BET]) -> None:
        r = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
        reels = (r[0], r[1], r[2])
        payout = slot_payout(reels, bet)
        bal = await self._gamble(interaction, bet, payout)
        if bal is None:
            return
        if payout > bet:
            outcome = f"You won **{payout - bet:,}** coins!"
        elif payout == bet:
            outcome = "A pair — you get your bet back."
        else:
            outcome = f"You lost **{bet:,}** coins."
        e = embed(description=f"🎰 | {' '.join(reels)} |\n{outcome}\nBalance: **{bal:,}**", color=OK_COLOR if payout >= bet else ERR_COLOR)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="rich", description="Richest members")
    @app_commands.guild_only()
    async def rich(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = await self.bot.db.fetchall(
            "SELECT user_id, balance FROM economy WHERE guild_id = ? AND balance > 0 ORDER BY balance DESC LIMIT 10",
            (interaction.guild.id,),
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — {COIN} **{int(b):,}**" for i, (uid, b) in enumerate(rows)]
        await interaction.response.send_message(embed=embed("💰 Richest members", "\n".join(lines) or "Nobody has coins yet."),
                                                allowed_mentions=discord.AllowedMentions.none())
