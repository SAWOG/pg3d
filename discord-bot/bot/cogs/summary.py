from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..chat_digest import Digest, RawMessage, finalize, summarize
from ..util import clip, embed, reply, staff_only

if TYPE_CHECKING:
    from ..main import HelperBot

ALL_LIMIT = 1000
LINE_CHARS = 300
EMBED_BUDGET = 3900
LANGUAGES: dict[str, str] = {"en": "English", "tr": "Türkçe", "pt": "Português", "es": "Español"}


def parse_count(text: str) -> int | None:
    text = text.strip().lower()
    if text in ("all", "hepsi", "tümü", "tumu"):
        return ALL_LIMIT
    return min(int(text), ALL_LIMIT) if text.isdigit() and int(text) > 0 else None


def _line(author: str, ts: int, text: str) -> str:
    return f"<t:{ts}:t> **{author}:** {clip(text, LINE_CHARS)}"


def render(digest: Digest, channel_name: str, lang: str) -> tuple[list[discord.Embed], discord.File | None]:
    top = ", ".join(f"{name} ({n})" for name, n in digest.participants[:5])
    head: list[str] = []
    if digest.start and digest.end:
        head.append(f"🕒 <t:{int(digest.start.timestamp())}:f> → <t:{int(digest.end.timestamp())}:R>")
    head.append(f"👥 **{len(digest.participants)}** people · {top}")
    head.append(f"💬 **{digest.total}** messages · {digest.skipped} filler skipped · {len(digest.blocks)} after merging")
    if digest.topics:
        head.append(f"🏷️ **Topics:** {', '.join(digest.topics)}")
    stats = embed(f"📝 #{channel_name} · last {digest.total} messages", "\n".join(head))
    if digest.questions:
        questions = "\n".join(f"• **{a}:** {clip(q, 150)}" for a, q in digest.questions)
        stats.add_field(name="❓ Questions asked", value=questions[:1024], inline=False)
    stats.set_footer(text=f"Auto-translated to {LANGUAGES.get(lang, lang)} · no AI, original order kept")

    lines = [_line(b.author, int(b.start.timestamp()), b.english or b.text) for b in digest.blocks]
    # Mesaj başına embed toplamı 6000 karakter: en yeni kısım ekranda, tamamı .txt olarak eklenir
    shown: list[str] = []
    used = 0
    for line in reversed(lines):
        if used + len(line) + 1 > EMBED_BUDGET:
            break
        shown.append(line)
        used += len(line) + 1
    shown.reverse()
    conv_title = "Conversation" if len(shown) == len(lines) else f"Conversation · last {len(shown)} of {len(lines)} (full text attached)"
    embeds = [stats, embed(conv_title, "\n".join(shown) or "Nothing to show.")]

    file = None
    if len(shown) < len(lines):
        full = "\n".join(
            f"[{b.start:%Y-%m-%d %H:%M}] {b.author}: {b.english or b.text}" for b in digest.blocks
        )
        file = discord.File(io.BytesIO(full.encode("utf-8")), filename=f"summary-{channel_name}.txt")
    return embeds, file


class Summary(commands.Cog):
    """Bir kanalın son N mesajını seçilen dile çevirip kısa bir özet halinde gösterir (yapay zeka yok)."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    async def _count_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        options = ["10", "25", "50", "100", "250", "all"]
        return [app_commands.Choice(name=o, value=o) for o in options if o.startswith(current.lower())][:25]

    @app_commands.command(name="summary", description="Summarize the last N messages of a channel (translated)")
    @app_commands.describe(
        messages=f"How many messages: a number or 'all' (max {ALL_LIMIT})",
        channel="Which channel (default: this one)",
        language="Summary language (default: English)",
    )
    @app_commands.autocomplete(messages=_count_autocomplete)
    @app_commands.choices(language=[app_commands.Choice(name=v, value=k) for k, v in LANGUAGES.items()])
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @staff_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    async def summary(
        self,
        interaction: discord.Interaction,
        messages: str,
        channel: discord.TextChannel | discord.Thread | None = None,
        language: app_commands.Choice[str] | None = None,
    ) -> None:
        count = parse_count(messages)
        if count is None:
            return await reply(interaction, f"Write a number (1-{ALL_LIMIT}) or `all`.", ok=False)
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.Thread)):
            return await reply(interaction, "This channel type isn't supported.", ok=False)
        member = interaction.user
        assert isinstance(member, discord.Member)
        if not target.permissions_for(member).read_message_history:
            return await reply(interaction, "You can't read that channel.", ok=False)
        if not target.permissions_for(target.guild.me).read_message_history:
            return await reply(interaction, f"I can't read {target.mention}.", ok=False)
        lang = language.value if language and language.value in LANGUAGES else "en"

        await interaction.response.defer(ephemeral=True, thinking=True)
        raw: list[RawMessage] = []
        async for m in target.history(limit=count):
            if m.author.bot or m.type not in (discord.MessageType.default, discord.MessageType.reply):
                continue
            raw.append(RawMessage(m.author.id, m.author.display_name, m.clean_content, m.created_at, len(m.attachments)))
        raw.reverse()  # history en yeniden eskiye döner; özet eskiden yeniye okunur
        if not raw:
            return await reply(interaction, "No messages to summarize.")

        digest = summarize(raw)
        translations = await self.bot.translator.translate_batch([b.text for b in digest.blocks], lang)
        for block, text in zip(digest.blocks, translations):
            block.english = text
        embeds, file = render(finalize(digest), target.name, lang)
        if file is not None:
            await interaction.followup.send(embeds=embeds, file=file, ephemeral=True)
        else:
            await interaction.followup.send(embeds=embeds, ephemeral=True)
