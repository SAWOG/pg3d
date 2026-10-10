from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..util import ERR_COLOR, OK_COLOR, clip, embed, get_bot, reply, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

K = "ticket."
OPEN_COOLDOWN = 30.0
TRANSCRIPT_LIMIT = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL,
    number     INTEGER NOT NULL,
    opened_at  INTEGER NOT NULL,
    closed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets (guild_id, owner_id, closed);
"""


def _is_ticket_staff(bot: HelperBot, member: discord.Member) -> bool:
    if member.guild_permissions.manage_channels:
        return True
    staff_role = bot.settings.get_int(member.guild.id, K + "staff_role")
    return any(r.id == staff_role for r in member.roles)


async def _ticket_owner(bot: HelperBot, channel_id: int) -> int | None:
    row = await bot.db.fetchone("SELECT owner_id FROM tickets WHERE channel_id = ? AND closed = 0", (channel_id,))
    return int(row[0]) if row else None


async def _transcript(channel: discord.TextChannel) -> bytes:
    lines: list[str] = []
    async for m in channel.history(limit=TRANSCRIPT_LIMIT, oldest_first=True):
        stamp = m.created_at.strftime("%Y-%m-%d %H:%M")
        text = m.clean_content or ""
        for e in m.embeds:
            text += f" [embed: {e.title or ''} {e.description or ''}]"
        for a in m.attachments:
            text += f" [file: {a.url}]"
        lines.append(f"[{stamp}] {m.author} ({m.author.id}): {text}")
    return "\n".join(lines).encode("utf-8")


async def close_ticket(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    """Ticket'ı kapatır: transcript'i log kanalına ve sahibine gönderir, kanalı siler."""
    bot = get_bot(interaction)
    row = await bot.db.fetchone("SELECT owner_id, number FROM tickets WHERE channel_id = ? AND closed = 0", (channel.id,))
    # Atomik: iki kişi aynı anda kapatırsa sadece biri işler
    if row is None or await bot.db.execute("UPDATE tickets SET closed = 1 WHERE channel_id = ? AND closed = 0", (channel.id,)) != 1:
        return await reply(interaction, "This ticket is already closed.", ok=False)
    owner_id, number = int(row[0]), int(row[1])
    await reply(interaction, "🔒 Closing this ticket in 5 seconds…", ephemeral=False)

    data = await _transcript(channel)
    filename = f"{channel.name}.txt"
    e = embed(f"🎫 Ticket #{number:04d} closed", color=ERR_COLOR)
    e.add_field(name="Opened by", value=f"<@{owner_id}>")
    e.add_field(name="Closed by", value=interaction.user.mention)
    await send_log(bot, channel.guild, K + "log_channel", e, discord.File(io.BytesIO(data), filename=filename))
    owner = channel.guild.get_member(owner_id)
    if owner is not None:
        try:
            await owner.send(embed=embed(f"Your ticket in {channel.guild.name} was closed", color=ERR_COLOR),
                             file=discord.File(io.BytesIO(data), filename=filename))
        except discord.HTTPException:
            pass
    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"Ticket closed by {interaction.user}")
    except discord.HTTPException as err:
        log.warning("Ticket kanalı silinemedi: %s", err)


class ConfirmClose(discord.ui.View):
    def __init__(self, channel: discord.TextChannel) -> None:
        super().__init__(timeout=60)
        self.channel = channel

    @discord.ui.button(label="Yes, close it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button[ConfirmClose]) -> None:
        self.stop()
        await close_ticket(interaction, self.channel)


class OpenTicketButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"ticket:open"):
    def __init__(self, label: str = "Open ticket") -> None:
        super().__init__(discord.ui.Button(label=label, emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket:open"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: Any) -> OpenTicketButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = get_bot(interaction)
        cog = bot.get_cog("Tickets")
        member = interaction.user
        if isinstance(cog, Tickets) and isinstance(member, discord.Member):
            await cog.open_ticket(interaction, member)


class CloseTicketButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"ticket:close"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:close"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: Any) -> CloseTicketButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = get_bot(interaction).get_cog("Tickets")
        if isinstance(cog, Tickets):
            await cog.request_close(interaction)


@app_commands.guild_only()
class Tickets(commands.GroupCog, group_name="ticket", group_description="Destek ticket sistemi"):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self._last_open: dict[int, float] = {}
        self._open_lock = asyncio.Lock()
        super().__init__()

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        self.bot.add_dynamic_items(OpenTicketButton, CloseTicketButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(OpenTicketButton, CloseTicketButton)

    # ---------- Akış ----------

    async def open_ticket(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild = member.guild
        s = self.bot.settings
        category = guild.get_channel(s.get_int(guild.id, K + "category"))
        staff_role = guild.get_role(s.get_int(guild.id, K + "staff_role"))
        if not isinstance(category, discord.CategoryChannel) or staff_role is None:
            return await reply(interaction, "Tickets aren't set up correctly. Please tell a moderator.", ok=False)

        now = time.monotonic()
        if now - self._last_open.get(member.id, 0.0) < OPEN_COOLDOWN:
            return await reply(interaction, "Please wait a bit before opening another ticket.", ok=False)
        await interaction.response.defer(ephemeral=True, thinking=True)

        async with self._open_lock:  # aynı kişi iki kez hızlıca basarsa iki kanal açılmasın
            row = await self.bot.db.fetchone(
                "SELECT channel_id FROM tickets WHERE guild_id = ? AND owner_id = ? AND closed = 0", (guild.id, member.id)
            )
            if row is not None:
                if guild.get_channel(int(row[0])) is not None:
                    return await reply(interaction, f"You already have an open ticket: <#{row[0]}>", ok=False)
                await self.bot.db.execute("UPDATE tickets SET closed = 1 WHERE channel_id = ?", (row[0],))
            self._last_open[member.id] = now
            number = s.get_int(guild.id, K + "counter") + 1
            await s.set(guild.id, K + "counter", number)

        overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                    read_message_history=True, manage_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, attach_files=True,
                                                  read_message_history=True, manage_channels=True, manage_messages=True),
        }
        try:
            channel = await guild.create_text_channel(
                f"ticket-{number:04d}", category=category, overwrites=overwrites, reason=f"Ticket by {member}",
                topic=f"Ticket #{number:04d} · {member} ({member.id})",
            )
        except discord.HTTPException as e:
            log.warning("Ticket kanalı açılamadı: %s", e)
            return await reply(interaction, "I couldn't create the ticket channel (missing permissions?).", ok=False)
        await self.bot.db.execute(
            "INSERT INTO tickets (channel_id, guild_id, owner_id, number, opened_at) VALUES (?, ?, ?, ?, ?)",
            (channel.id, guild.id, member.id, number, int(time.time())),
        )
        view = discord.ui.View(timeout=None)
        view.add_item(CloseTicketButton())
        welcome = s.get_str(guild.id, K + "welcome", "Thanks for opening a ticket! Describe your issue and our team will help you soon.")
        await channel.send(
            content=f"{member.mention} {staff_role.mention}",
            embed=embed(f"🎫 Ticket #{number:04d}", welcome, OK_COLOR),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=[member], roles=[staff_role], everyone=False),
        )
        await reply(interaction, f"Your ticket is ready: {channel.mention}")

    async def request_close(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        member = interaction.user
        if not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            return
        owner_id = await _ticket_owner(self.bot, channel.id)
        if owner_id is None:
            return await reply(interaction, "This isn't an open ticket.", ok=False)
        if member.id != owner_id and not _is_ticket_staff(self.bot, member):
            return await reply(interaction, "Only the ticket owner or staff can close it.", ok=False)
        await interaction.response.send_message("Close this ticket?", view=ConfirmClose(channel), ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.db.execute("UPDATE tickets SET closed = 1 WHERE channel_id = ?", (channel.id,))

    # ---------- Komutlar ----------

    @app_commands.command(name="setup", description="Ticket panelini gönder (Yönetici)")
    @app_commands.describe(channel="Panelin gönderileceği kanal", category="Ticket kanallarının açılacağı kategori",
                           staff_role="Ticket'ları görecek yetkili rolü", log_channel="Transcript'lerin gideceği kanal",
                           title="Panel başlığı", message="Panel açıklaması", welcome="Ticket açılınca yazılacak mesaj")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, category: discord.CategoryChannel,
                    staff_role: discord.Role, log_channel: discord.TextChannel | None = None,
                    title: str = "🎫 Support", message: str = "Need help? Press the button below to open a private ticket.",
                    welcome: str | None = None) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        s = self.bot.settings
        await s.set(gid, K + "category", category.id)
        await s.set(gid, K + "staff_role", staff_role.id)
        if log_channel is not None:
            await s.set(gid, K + "log_channel", log_channel.id)
        if welcome:
            await s.set(gid, K + "welcome", clip(welcome, 2000))
        view = discord.ui.View(timeout=None)
        view.add_item(OpenTicketButton())
        msg = await channel.send(embed=embed(clip(title, 256), clip(message, 4000)), view=view)
        await reply(interaction, f"Ticket paneli gönderildi: {msg.jump_url}")

    async def _staff_in_ticket(self, interaction: discord.Interaction) -> discord.TextChannel | None:
        channel = interaction.channel
        member = interaction.user
        if not isinstance(channel, discord.TextChannel) or await _ticket_owner(self.bot, channel.id) is None:
            await reply(interaction, "Use this inside an open ticket.", ok=False)
            return None
        if not isinstance(member, discord.Member) or not _is_ticket_staff(self.bot, member):
            await reply(interaction, "Only staff can do this.", ok=False)
            return None
        return channel

    @app_commands.command(name="add", description="Add a member to this ticket (staff)")
    async def add(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if (channel := await self._staff_in_ticket(interaction)) is None:
            return
        await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        await reply(interaction, f"{member.mention} was added to the ticket.", ephemeral=False)

    @app_commands.command(name="remove", description="Remove a member from this ticket (staff)")
    async def remove(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if (channel := await self._staff_in_ticket(interaction)) is None:
            return
        if member.id == await _ticket_owner(self.bot, channel.id):
            return await reply(interaction, "You can't remove the ticket owner.", ok=False)
        await channel.set_permissions(member, overwrite=None)
        await reply(interaction, f"{member.mention} was removed from the ticket.", ephemeral=False)

    @app_commands.command(name="close", description="Close this ticket")
    async def close(self, interaction: discord.Interaction) -> None:
        await self.request_close(interaction)
