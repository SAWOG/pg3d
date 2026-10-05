from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from ..storage import Status
from ..suggestions import DecisionResult, SortOrder, Suggestion, apply_decision, collect_pending, fill_summaries
from ..util import clip, is_staff

if TYPE_CHECKING:
    from ..main import HelperBot

log = logging.getLogger(__name__)

PAGE_SIZE = 10
TIMEOUT = 14 * 60  # ephemeral mesaj token'ı 15 dk geçerli
SORT_LABELS: dict[str, str] = {"votes": "oy", "newest": "en yeni", "oldest": "en eski"}
RESULT_TEXT: dict[DecisionResult, str] = {
    "ok": "",
    "taken": "başka yetkili zaten karar vermiş",
    "deleted": "mesaj silinmiş",
    "failed": "cevap gönderilemedi (botun kanalda mesaj/embed izni var mı?)",
}
STATUS_TEXT: dict[Status, str] = {"accepted": "kabul edildi", "rejected": "reddedildi", "dismissed": "cevapsız kapatıldı"}


class DecisionModal(discord.ui.Modal):
    reason: discord.ui.TextInput[DecisionModal] = discord.ui.TextInput(
        label="Açıklama (opsiyonel)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Öneri kanalında cevap olarak görünecek",
    )

    def __init__(self, panel: ReviewPanel, status: Status, ids: frozenset[int]) -> None:
        verb = "Kabul et" if status == "accepted" else "Reddet"
        super().__init__(title=f"{verb} · {len(ids)} öneri", timeout=TIMEOUT)
        self.panel = panel
        self.status: Status = status
        self.ids = ids

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.panel.decide(interaction, self.status, self.ids, self.reason.value.strip())


class SuggestionSelect(discord.ui.Select["ReviewPanel"]):
    def __init__(self, items: list[Suggestion], offset: int) -> None:
        options = [
            discord.SelectOption(
                label=clip(f"{offset + i}. {s.summary or s.text}", 100),
                value=str(s.message_id),
                description=clip(f"👍 {s.up} · 👎 {s.down} · {s.author}", 100),
            )
            for i, s in enumerate(items, 1)
        ]
        super().__init__(
            placeholder="İşlem yapılacak önerileri seç…",
            min_values=0,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.selected = frozenset(int(v) for v in self.values)
        await interaction.response.defer()


class ReviewPanel(discord.ui.View):
    def __init__(
        self,
        bot: HelperBot,
        owner_id: int,
        channel: discord.TextChannel,
        items: list[Suggestion],
        *,
        min_votes: int,
        sort: SortOrder,
    ) -> None:
        super().__init__(timeout=TIMEOUT)
        self.bot = bot
        self.owner_id = owner_id
        self.channel = channel
        self.items = items
        self.min_votes = min_votes
        self.sort: SortOrder = sort
        self.page = 0
        self.selected: frozenset[int] = frozenset()
        self.status_line = ""
        self.origin: discord.Interaction | None = None
        self._select: SuggestionSelect | None = None

    # ---------- Görünüm ----------

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self.items) // PAGE_SIZE))

    def _page_items(self) -> list[Suggestion]:
        start = self.page * PAGE_SIZE
        return self.items[start : start + PAGE_SIZE]

    async def render(self) -> discord.Embed:
        self.page = min(self.page, self.page_count - 1)
        self.selected = frozenset()
        items = self._page_items()
        await fill_summaries(items, self.bot.translator)

        if self._select is not None:
            self.remove_item(self._select)
            self._select = None
        if items:
            self._select = SuggestionSelect(items, self.page * PAGE_SIZE)
            self.add_item(self._select)

        empty = not items
        for button in (self.accept, self.reject, self.dismiss):
            button.disabled = empty
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.page_count - 1

        lines: list[str] = [self.status_line] if self.status_line else []
        if empty:
            lines.append("Bekleyen öneri yok 🎉")
        for i, s in enumerate(items, self.page * PAGE_SIZE + 1):
            lang = f" · `{s.lang}`" if s.lang not in {"tr", "?"} else ""
            lines.append(
                f"**{i}.** {s.summary}\n"
                f"👍 **{s.up}** · 👎 **{s.down}** · *{s.author}* · <t:{int(s.created_at.timestamp())}:R>{lang} · [mesaj]({s.url})"
            )
        embed = discord.Embed(
            title=f"#{self.channel.name} · {len(self.items)} bekleyen öneri",
            description="\n\n".join(lines)[:4096],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Sayfa {self.page + 1}/{self.page_count} · sıralama: {SORT_LABELS[self.sort]}")
        return embed

    async def _redraw(self, interaction: discord.Interaction) -> None:
        embed = await self.render()
        await interaction.edit_original_response(embed=embed, view=self)

    # ---------- Güvenlik ----------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not is_staff(interaction.user, self.bot.config.staff_role_ids):
            await interaction.response.send_message("Bu panel senin değil.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.origin is None:
            return
        try:
            await self.origin.edit_original_response(content="⏱️ Panelin süresi doldu, `/summary` ile tekrar aç.", view=None)
        except discord.HTTPException:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[ReviewPanel]) -> None:
        log.exception("Panel hatası", exc_info=error)
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send("Beklenmeyen bir hata oluştu.", ephemeral=True)

    # ---------- İşlemler ----------

    async def decide(self, interaction: discord.Interaction, status: Status, ids: frozenset[int], reason: str) -> None:
        await interaction.response.defer()
        # Sadece sunucudaki listede hâlâ bekleyen öneriler işlenir; istemciden gelen ID'ye güvenilmez
        targets = [s for s in self.items if s.message_id in ids]
        done: set[int] = set()
        errors: list[str] = []
        for s in targets:
            result = await apply_decision(self.channel, self.bot.store, self.bot.config, s, status, reason, interaction.user)
            if result != "failed":
                done.add(s.message_id)
            if result != "ok":
                errors.append(f"• {clip(s.summary or s.text, 50)}: {RESULT_TEXT[result]}")

        self.items = [s for s in self.items if s.message_id not in done]
        ok = len(targets) - len(errors)
        self.status_line = f"**{ok} öneri {STATUS_TEXT[status]}.**" + ("\n⚠️ " + "\n".join(errors) if errors else "")
        await self._redraw(interaction)

    async def _open_modal(self, interaction: discord.Interaction, status: Status) -> None:
        if not self.selected:
            await interaction.response.send_message("Önce listeden en az bir öneri seç.", ephemeral=True)
            return
        await interaction.response.send_modal(DecisionModal(self, status, self.selected))

    @discord.ui.button(label="Kabul et", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        await self._open_modal(interaction, "accepted")

    @discord.ui.button(label="Reddet", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        await self._open_modal(interaction, "rejected")

    @discord.ui.button(label="Cevapsız kapat", emoji="🙈", style=discord.ButtonStyle.secondary, row=1)
    async def dismiss(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        if not self.selected:
            await interaction.response.send_message("Önce listeden en az bir öneri seç.", ephemeral=True)
            return
        await self.decide(interaction, "dismissed", self.selected, "")

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        await interaction.response.defer()
        self.page = max(0, self.page - 1)
        self.status_line = ""
        await self._redraw(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        await interaction.response.defer()
        self.page = min(self.page_count - 1, self.page + 1)
        self.status_line = ""
        await self._redraw(interaction)

    @discord.ui.button(label="Yenile", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def reload(self, interaction: discord.Interaction, _: discord.ui.Button[ReviewPanel]) -> None:
        await interaction.response.defer()
        self.items = await collect_pending(
            self.channel, self.bot.store, self.bot.config, min_votes=self.min_votes, sort=self.sort
        )
        self.status_line = "🔄 Liste yenilendi."
        await self._redraw(interaction)
