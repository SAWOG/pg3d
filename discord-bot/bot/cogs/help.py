from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..util import clip, embed

if TYPE_CHECKING:
    from ..main import HelperBot

# Cog sınıf adı -> kategori başlığı (sıra önemli)
CATEGORIES: dict[str, str] = {
    "Music": "🎵 Music",
    "Levels": "📈 Levels",
    "Economy": "🪙 Economy",
    "Fun": "🎉 Fun",
    "Invites": "📨 Invites",
    "TempVoice": "🔊 Temp voice",
    "Tickets": "🎫 Tickets",
    "Moderation": "🛡️ Moderation",
    "Automod": "🤖 Automod",
    "Welcome": "👋 Welcome",
    "Roles": "🎭 Role panels",
    "Verification": "🔐 Verification",
    "Stats": "📊 Server stats",
    "YouTube": "📺 YouTube alerts",
    "Suggestions": "💡 Suggestions",
    "Setup": "⚙️ Setup",
}


def _walk(cmd: app_commands.Command[Any, ..., Any] | app_commands.Group) -> list[str]:
    if isinstance(cmd, app_commands.Group):
        out: list[str] = []
        for sub in cmd.commands:
            out.extend(_walk(sub))
        return out
    return [f"`/{cmd.qualified_name}`"]


class Help(commands.Cog):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="List all commands")
    async def help(self, interaction: discord.Interaction) -> None:
        owner: dict[str, str] = {}
        for name, cog in self.bot.cogs.items():
            for cmd in cog.get_app_commands():
                owner[cmd.name] = name
            for cmd in getattr(cog, "extra_commands", ()):  # Fun gibi dinamik eklenen komutlar
                owner[cmd.name] = name

        grouped: dict[str, list[str]] = {}
        for cmd in self.bot.tree.get_commands(type=discord.AppCommandType.chat_input):
            assert isinstance(cmd, (app_commands.Command, app_commands.Group))
            title = CATEGORIES.get(owner.get(cmd.name, ""), "📦 Other")
            grouped.setdefault(title, []).extend(_walk(cmd))

        e = embed("📖 Commands", "Admin commands are only visible to members with the right permissions.")
        for title in [*CATEGORIES.values(), "📦 Other"]:
            if grouped.get(title):
                e.add_field(name=title, value=clip(" ".join(sorted(set(grouped[title]))), 1024), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)
