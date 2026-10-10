"""Terminalden kanal özeti. Botun çalışıyor olması gerekmez: botun token'ıyla sadece mesajları okur.

Kullanım:  python -m bot.cli [kanal] [sayı|all] [en|tr|pt|es]
Sonra açık kalır; her satıra yeni bir istek yazılabilir.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import discord

from .chat_digest import Digest
from .config import ROOT, Config
from .summary_service import LANGUAGES, build_digest, parse_count
from .translate import Translator

DEFAULT_COUNT = "50"
SAVE_OVER_LINES = 60
SAVE_DIR = ROOT / "ozetler"
EXIT_WORDS = {"q", "quit", "exit", "çık", "cik", "çıkış"}
HELP = """Yazım:  <kanal> [sayı|all] [dil]
  general-english 10        son 10 mesajın İngilizce özeti
  general-br all tr         son 1000 mesajın Türkçe özeti
  kanallar                  kanal listesi
  çık                       kapat"""


def parse_line(line: str) -> tuple[str, int, str] | str:
    """(kanal, sayı, dil) veya hata mesajı."""
    parts = line.split()
    if not parts:
        return HELP
    channel, rest = parts[0].lstrip("#"), parts[1:]
    count_text, lang = DEFAULT_COUNT, "en"
    for p in rest:
        if p.lower() in LANGUAGES:
            lang = p.lower()
        else:
            count_text = p
    count = parse_count(count_text)
    if count is None:
        return f"'{count_text}' geçerli değil: bir sayı veya all yaz."
    return channel, count, lang


def resolve_channel(channels: list[discord.TextChannel], query: str) -> discord.TextChannel | list[str]:
    """Tam ad, ID veya ad parçasıyla kanal bulur. Bulamazsa aday adlarını döndürür."""
    q = query.lower()
    for ch in channels:
        if ch.name.lower() == q or str(ch.id) == q:
            return ch
    matches = [ch for ch in channels if q in ch.name.lower()]
    if len(matches) == 1:
        return matches[0]
    return [ch.name for ch in matches]


def _time(dt: datetime, with_date: bool) -> str:
    return dt.astimezone().strftime("%d.%m %H:%M" if with_date else "%H:%M")


def format_digest(d: Digest, channel_name: str, lang: str) -> list[str]:
    multi_day = bool(d.start and d.end and d.start.astimezone().date() != d.end.astimezone().date())
    people = ", ".join(f"{n} {c}" for n, c in d.participants[:6])
    lines = [f"=== #{channel_name} · son {d.total} mesaj · {LANGUAGES.get(lang, lang)} ==="]
    if d.start and d.end:
        lines.append(f"Zaman   : {_time(d.start, True)} -> {_time(d.end, multi_day)}")
    lines.append(f"Kişiler : {len(d.participants)} ({people})")
    lines.append(f"Mesaj   : {d.total} ({d.skipped} boş mesaj atlandı, birleşince {len(d.blocks)} satır)")
    if d.topics:
        lines.append(f"Konular : {', '.join(d.topics)}")
    if d.questions:
        lines.append("Sorular :")
        lines += [f"  - {a}: {q}" for a, q in d.questions]
    lines.append("--- Konuşma ---")
    lines += [f"{_time(b.start, multi_day)} {b.author}: {b.english or b.text}" for b in d.blocks]
    return lines


async def _pick_guild(client: discord.Client, guild_id: int) -> discord.Guild:
    if guild_id:
        return await client.fetch_guild(guild_id)
    guilds = [g async for g in client.fetch_guilds(limit=10)]
    if len(guilds) != 1:
        names = ", ".join(g.name for g in guilds) or "yok"
        raise SystemExit(f"Bot birden fazla sunucuda ({names}). .env içine GUILD_ID yaz.")
    return await client.fetch_guild(guilds[0].id)


async def _handle(line: str, channels: list[discord.TextChannel], translator: Translator) -> None:
    cmd = line.strip().lower()
    if cmd in ("kanallar", "channels"):
        print("  " + "\n  ".join(sorted(f"#{c.name}" for c in channels)))
        return
    if cmd in ("yardım", "yardim", "help", "?"):
        print(HELP)
        return
    parsed = parse_line(line)
    if isinstance(parsed, str):
        print(parsed)
        return
    query, count, lang = parsed
    found = resolve_channel(channels, query)
    if isinstance(found, list):
        print(f"Birden fazla kanal eşleşti: {', '.join(found)}" if found else f"'{query}' adında kanal yok. 'kanallar' yaz.")
        return
    print(f"#{found.name} okunuyor ({count} mesaj)...")
    try:
        digest = await build_digest(found, count, translator, lang)
    except discord.Forbidden:
        print(f"Bot #{found.name} kanalını göremiyor (kanal izinlerine botu ekle).")
        return
    if digest is None:
        print("Özetlenecek mesaj yok.")
        return
    lines = format_digest(digest, found.name, lang)
    print("\n".join(lines))
    if len(lines) > SAVE_OVER_LINES:
        SAVE_DIR.mkdir(exist_ok=True)
        path = SAVE_DIR / f"{found.name}-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n(Uzun özet ayrıca kaydedildi: {path})")


async def run(argv: list[str]) -> None:
    config = Config.load()
    client = discord.Client(intents=discord.Intents.none())
    translator = Translator(config.translate_enabled)
    try:
        await client.login(config.discord_token)
        guild = await _pick_guild(client, config.guild_id)
        channels = [c for c in await guild.fetch_channels() if isinstance(c, discord.TextChannel)]
        print(f"{guild.name} · {len(channels)} kanal. 'yardım' yazarak örnekleri görebilirsin.\n")
        if argv:
            await _handle(" ".join(argv), channels, translator)
        while True:
            try:
                line = await asyncio.to_thread(input, "\nözet> ")
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip().lower() in EXIT_WORDS:
                break
            if line.strip():
                await _handle(line, channels, translator)
    except discord.LoginFailure:
        print("Token geçersiz. .env içindeki DISCORD_TOKEN'ı kontrol et.")
    finally:
        await translator.close()
        await client.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(run(sys.argv[1:]))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
