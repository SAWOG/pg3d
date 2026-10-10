from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..util import ERR_COLOR, OK_COLOR, clip, embed, get_bot, reply, require_manage_guild, role_assignable, send_log

if TYPE_CHECKING:
    from ..main import HelperBot

K = "verify."


async def _grant(interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
    bot = get_bot(interaction)
    await member.add_roles(role, reason="Verification")
    await reply(interaction, "✅ You're verified, welcome!")
    e = embed("✅ Verified", f"{member.mention} (`{member.id}`)", OK_COLOR)
    await send_log(bot, member.guild, "log.channel", e)


class CaptchaModal(discord.ui.Modal, title="Verification"):
    def __init__(self, role: discord.Role) -> None:
        super().__init__(timeout=300)
        a, b = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
        self._answer = str(a + b)  # cevap sadece sunucuda tutulur, istemciye gönderilmez
        self._role = role
        self.answer: discord.ui.TextInput[CaptchaModal] = discord.ui.TextInput(label=f"What is {a} + {b}?", max_length=3)
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        assert isinstance(member, discord.Member)
        if self.answer.value.strip() != self._answer:
            return await reply(interaction, "Wrong answer, press the button to try again.", ok=False)
        await _grant(interaction, member, self._role)


class VerifyButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"verify:go"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(label="Verify", emoji="✅", style=discord.ButtonStyle.success, custom_id="verify:go"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: Any) -> VerifyButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = get_bot(interaction)
        member = interaction.user
        if interaction.guild is None or not isinstance(member, discord.Member):
            return
        gid = interaction.guild.id
        role = interaction.guild.get_role(bot.settings.get_int(gid, K + "role"))
        if role is None or role_assignable(role) is not None:
            return await reply(interaction, "Verification isn't set up correctly. Please tell a moderator.", ok=False)
        if role in member.roles:
            return await reply(interaction, "You're already verified.")

        min_days = bot.settings.get_int(gid, K + "min_age_days")
        age_days = (datetime.now(timezone.utc) - member.created_at).days
        if age_days < min_days:
            e = embed("⛔ Verification blocked (new account)", f"{member.mention} · account {age_days} days old", ERR_COLOR)
            await send_log(bot, member.guild, "log.channel", e)
            return await reply(interaction, f"Your account must be at least {min_days} days old to join.", ok=False)

        if bot.settings.get_bool(gid, K + "captcha", True):
            await interaction.response.send_modal(CaptchaModal(role))
        else:
            await _grant(interaction, member, role)


@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
class Verification(commands.GroupCog, group_name="verify", group_description="Doğrulama (yeni hesap engeli + captcha)"):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(VerifyButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(VerifyButton)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage_guild(interaction)

    @app_commands.command(name="setup", description="Doğrulama panelini gönder")
    @app_commands.describe(channel="Panel kanalı", role="Doğrulanınca verilecek rol",
                           min_account_days="Hesap en az kaç günlük olmalı (0 = kontrol yok)",
                           captcha="Basit toplama sorusu sorulsun mu", message="Panel açıklaması")
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role,
                    min_account_days: app_commands.Range[int, 0, 365] = 7, captcha: bool = True,
                    message: str | None = None) -> None:
        actor = interaction.user
        assert isinstance(actor, discord.Member) and interaction.guild is not None
        if err := role_assignable(role):
            return await reply(interaction, err, ok=False)
        if actor.id != interaction.guild.owner_id and role >= actor.top_role:
            return await reply(interaction, "Bu rol senin en yüksek rolünden yüksek.", ok=False)
        gid = interaction.guild.id
        await self.bot.settings.set(gid, K + "role", role.id)
        await self.bot.settings.set(gid, K + "min_age_days", min_account_days)
        await self.bot.settings.set(gid, K + "captcha", captcha)
        view = discord.ui.View(timeout=None)
        view.add_item(VerifyButton())
        text = clip(message, 2000) if message else "Press **Verify** to get access to the server."
        msg = await channel.send(embed=embed("🔐 Verification", text, OK_COLOR), view=view)
        await reply(
            interaction,
            f"Panel gönderildi: {msg.jump_url}\nİpucu: @everyone rolünden kanalları görme iznini kaldırıp sadece {role.mention} rolüne ver.",
        )
