from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..util import clip, embed, get_bot, reply, require_manage_guild, role_assignable

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS role_buttons (
    message_id INTEGER NOT NULL,
    guild_id   INTEGER NOT NULL,
    role_id    INTEGER NOT NULL,
    PRIMARY KEY (message_id, role_id)
);
"""


class RoleButton(discord.ui.DynamicItem[discord.ui.Button[Any]], template=r"rr:(?P<role_id>\d{15,22})"):
    """Bot yeniden başlasa da çalışan rol butonu (custom_id = rr:<rol_id>)."""

    def __init__(self, role_id: int, label: str = "", emoji: str | None = None) -> None:
        super().__init__(discord.ui.Button(label=label or None, emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=f"rr:{role_id}"))
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: Any) -> RoleButton:
        return cls(int(match["role_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = get_bot(interaction)
        member = interaction.user
        if interaction.guild is None or interaction.message is None or not isinstance(member, discord.Member):
            return
        # custom_id istemciden gelir: bu rolün gerçekten bu panele kayıtlı olduğu doğrulanır
        row = await bot.db.fetchone(
            "SELECT 1 FROM role_buttons WHERE message_id = ? AND role_id = ? AND guild_id = ?",
            (interaction.message.id, self.role_id, interaction.guild.id),
        )
        role = interaction.guild.get_role(self.role_id)
        if row is None or role is None:
            return await reply(interaction, "This role button is no longer valid.", ok=False)
        if role_assignable(role) is not None:
            return await reply(interaction, "I can't manage that role anymore. Please tell a moderator.", ok=False)
        if role in member.roles:
            await member.remove_roles(role, reason="Role button")
            await reply(interaction, f"Removed {role.mention}.")
        else:
            await member.add_roles(role, reason="Role button")
            await reply(interaction, f"Added {role.mention}.")


@app_commands.default_permissions(manage_roles=True)
@app_commands.guild_only()
class Roles(commands.GroupCog, group_name="roles", group_description="Butonla rol alma panelleri"):
    def __init__(self, bot: HelperBot) -> None:
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        await self.bot.db.script(_SCHEMA)
        self.bot.add_dynamic_items(RoleButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleButton)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.permissions.manage_roles:
            raise app_commands.MissingPermissions(["manage_roles"])
        return await require_manage_guild(interaction)

    @app_commands.command(name="panel", description="Üyelerin butona basıp rol alabileceği bir panel gönder (en fazla 5 rol)")
    @app_commands.describe(channel="Panelin gönderileceği kanal", title="Başlık", description="Açıklama",
                           emojis="Butonlardaki emojiler, sırayla virgülle (opsiyonel)")
    async def panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, role1: discord.Role,
        role2: discord.Role | None = None, role3: discord.Role | None = None, role4: discord.Role | None = None,
        role5: discord.Role | None = None, description: str | None = None, emojis: str | None = None,
    ) -> None:
        actor = interaction.user
        assert isinstance(actor, discord.Member) and interaction.guild is not None
        roles = list(dict.fromkeys(r for r in (role1, role2, role3, role4, role5) if r is not None))
        for role in roles:
            if err := role_assignable(role):
                return await reply(interaction, f"{role.mention}: {err}", ok=False)
            # Kimse kendi rolünden yüksek bir rolü dağıtan panel kuramaz
            if actor.id != interaction.guild.owner_id and role >= actor.top_role:
                return await reply(interaction, f"{role.mention} senin en yüksek rolünden yüksek.", ok=False)
        emoji_list = [e.strip() for e in (emojis or "").split(",")]
        view = discord.ui.View(timeout=None)
        for i, role in enumerate(roles):
            emoji = emoji_list[i] if i < len(emoji_list) and emoji_list[i] else None
            view.add_item(RoleButton(role.id, label=clip(role.name, 80), emoji=emoji))

        lines = [description or "Click a button to get or remove a role."]
        lines += [f"{emoji_list[i] if i < len(emoji_list) and emoji_list[i] else '•'} {r.mention}" for i, r in enumerate(roles)]
        try:
            msg = await channel.send(embed=embed(clip(title, 256), "\n".join(lines)), view=view)
        except discord.HTTPException as e:
            return await reply(interaction, f"Panel gönderilemedi (emoji geçersiz olabilir veya izin yok): {e.text}", ok=False)
        for role in roles:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO role_buttons (message_id, guild_id, role_id) VALUES (?, ?, ?)",
                (msg.id, interaction.guild.id, role.id),
            )
        await reply(interaction, f"Panel gönderildi: {msg.jump_url}")
