from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..util import INFO_COLOR, clip, embed, reply

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

NEKOS_URL = "https://nekos.best/api/v2/{category}"

# Nekotina tarzı etkileşimler: komut adı -> fiil (nekos.best kategorisiyle aynı)
ACTIONS: dict[str, str] = {
    "hug": "hugs", "pat": "pats", "kiss": "kisses", "slap": "slaps",
    "cuddle": "cuddles", "poke": "pokes", "bite": "bites", "highfive": "high-fives",
}
Emote = Literal["cry", "dance", "smile", "blush", "laugh", "wave", "sleep", "shrug", "pout", "happy"]
EMOTE_TEXT: dict[str, str] = {
    "cry": "is crying", "dance": "is dancing", "smile": "is smiling", "blush": "is blushing", "laugh": "is laughing",
    "wave": "waves", "sleep": "is sleeping", "shrug": "shrugs", "pout": "is pouting", "happy": "is happy",
}
EIGHT_BALL = (
    "It is certain.", "Without a doubt.", "You may rely on it.", "Yes, definitely.", "Most likely.",
    "Outlook good.", "Ask again later.", "Cannot predict now.", "Don't count on it.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
)
NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")


class Fun(commands.Cog):
    """Nekotina / FlaviBot tarzı eğlence ve bilgi komutları."""

    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        self.extra_commands: list[app_commands.Command[Fun, ..., None]] = []

    async def cog_load(self) -> None:
        for name, verb in ACTIONS.items():
            cmd = self._make_action(name, verb)
            self.bot.tree.add_command(cmd)
            self.extra_commands.append(cmd)

    async def cog_unload(self) -> None:
        for cmd in self.extra_commands:
            self.bot.tree.remove_command(cmd.name)

    async def _gif(self, category: str) -> str | None:
        try:
            async with self.bot.http_session.get(NEKOS_URL.format(category=category)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
            url = data["results"][0]["url"]
            return url if isinstance(url, str) and url.startswith("https://") else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError, TypeError) as e:
            log.warning("nekos.best isteği başarısız: %s", e)
            return None

    def _make_action(self, name: str, verb: str) -> app_commands.Command[Fun, ..., None]:
        async def callback(interaction: discord.Interaction, user: discord.Member) -> None:
            if user.id == interaction.user.id:
                text = f"**{interaction.user.display_name}** {verb} themselves… 🥲"
            else:
                text = f"**{interaction.user.display_name}** {verb} **{user.display_name}**!"
            await interaction.response.defer()
            e = embed(description=text, color=discord.Color.pink())
            if url := await self._gif(name):
                e.set_image(url=url)
            await interaction.followup.send(content=user.mention, embed=e,
                                            allowed_mentions=discord.AllowedMentions(users=[user], everyone=False, roles=False))

        callback = app_commands.describe(user="Who?")(callback)
        cmd: app_commands.Command[Fun, ..., None] = app_commands.Command(
            name=name, description=f"{name.capitalize()} someone (anime GIF)", callback=callback
        )
        cmd.guild_only = True
        return cmd

    @app_commands.command(name="emote", description="Express yourself with an anime GIF")
    @app_commands.guild_only()
    async def emote(self, interaction: discord.Interaction, feeling: Emote) -> None:
        await interaction.response.defer()
        if feeling not in EMOTE_TEXT:
            return await reply(interaction, "Unknown emote.", ok=False)
        e = embed(description=f"**{interaction.user.display_name}** {EMOTE_TEXT[feeling]}", color=discord.Color.pink())
        if url := await self._gif(feeling):
            e.set_image(url=url)
        await interaction.followup.send(embed=e)

    @app_commands.command(name="8ball", description="Ask the magic 8-ball")
    async def eight_ball(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.send_message(embed=embed(description=f"🎱 **{clip(question, 200)}**\n{random.choice(EIGHT_BALL)}"))

    @app_commands.command(name="roll", description="Roll a dice")
    async def roll(self, interaction: discord.Interaction, sides: app_commands.Range[int, 2, 1000] = 6) -> None:
        await interaction.response.send_message(f"🎲 You rolled **{random.randint(1, sides)}** (1-{sides})")

    @app_commands.command(name="choose", description="Let me choose for you (comma separated)")
    async def choose(self, interaction: discord.Interaction, options: str) -> None:
        items = [o.strip() for o in options.split(",") if o.strip()]
        if len(items) < 2:
            return await reply(interaction, "Give me at least 2 options separated by commas.", ok=False)
        await interaction.response.send_message(f"🤔 I choose **{clip(random.choice(items), 200)}**",
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="avatar", description="Show someone's avatar")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        target = user or interaction.user
        e = embed(f"{target.display_name}'s avatar")
        e.set_image(url=target.display_avatar.with_size(1024).url)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="userinfo", description="Info about a member")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        m = member or interaction.user
        assert isinstance(m, discord.Member)
        e = embed(str(m), color=m.color if m.color.value else INFO_COLOR)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="ID", value=str(m.id))
        e.add_field(name="Created", value=f"<t:{int(m.created_at.timestamp())}:R>")
        if m.joined_at:
            e.add_field(name="Joined", value=f"<t:{int(m.joined_at.timestamp())}:R>")
        roles = [r.mention for r in reversed(m.roles) if not r.is_default()]
        e.add_field(name=f"Roles ({len(roles)})", value=clip(" ".join(roles), 1000) or "—", inline=False)
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="serverinfo", description="Info about this server")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        assert g is not None
        e = embed(g.name)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="Owner", value=f"<@{g.owner_id}>")
        e.add_field(name="Members", value=f"{g.member_count:,}" if g.member_count else "?")
        e.add_field(name="Created", value=f"<t:{int(g.created_at.timestamp())}:R>")
        e.add_field(name="Channels", value=f"{len(g.text_channels)} text · {len(g.voice_channels)} voice")
        e.add_field(name="Roles", value=str(len(g.roles)))
        e.add_field(name="Boosts", value=f"{g.premium_subscription_count} (level {g.premium_tier})")
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="poll", description="Create a quick poll (2-5 options)")
    @app_commands.guild_only()
    async def poll(self, interaction: discord.Interaction, question: str, option1: str, option2: str,
                   option3: str | None = None, option4: str | None = None, option5: str | None = None) -> None:
        options = [o for o in (option1, option2, option3, option4, option5) if o]
        lines = [f"{NUMBER_EMOJIS[i]} {clip(o, 200)}" for i, o in enumerate(options)]
        e = embed(f"📊 {clip(question, 250)}", "\n".join(lines))
        e.set_footer(text=f"Poll by {interaction.user.display_name}")
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())
        msg = await interaction.original_response()
        for i in range(len(options)):
            await msg.add_reaction(NUMBER_EMOJIS[i])
