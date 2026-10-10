# SAWOG Bot: hepsi bir arada

Sunucudaki 22 botun işini tek bot yapar. Yapay zeka kullanmaz, API anahtarı gerekmez.
Token dışındaki bütün ayarlar Discord içinde slash komutlarıyla yapılır ve `bot.db` dosyasında saklanır.

## Hangi botun yerine ne var?

| Eski bot | Bu botta | Ayar komutu |
|---|---|---|
| **Jockie Music ×3, Rythm** | `/play` `/skip` `/stop` `/pause` `/resume` `/queue` `/nowplaying` `/volume` `/loop` `/shuffle` `/remove` | — |
| **Dyno, Carl, FlaviBot** (moderasyon) | `/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarnings` `/purge` `/slowmode` `/lock` `/unlock` | `/setup modlog`, `/setup warns` |
| **Dyno, Carl** (automod) | Küfür/yasaklı kelime, davet linki, link, spam/flood, toplu etiket, büyük harf | `/automod …` |
| **Carl, Dyno** (loglar) | Silinen/düzenlenen mesaj, giriş/çıkış, ban, rol/isim değişikliği, ses kanalı | `/setup logs` |
| **Carl** (hoş geldin, otomatik rol, rol menüsü) | Hoş geldin/güle güle mesajı, otomatik rol, butonla rol alma paneli | `/welcome …`, `/roles panel` |
| **Tickety, SAWOG TICKETS** | Butonla ticket açma, özel kanal, kapatınca transcript (.txt) | `/ticket setup` |
| **Invite Tracker, InviteLogger** | Kim kimi davet etti, ayrılanlar, sahte (yeni) hesaplar, tekrar girenler sayılmaz | `/invites channel` |
| **Arcane** | Mesajla XP, `/rank`, `/leaderboard`, seviye rolleri | `/levels …` |
| **OwO, Nekotina** (ekonomi) | `/balance` `/daily` `/work` `/give` `/coinflip` `/slots` `/rich` | — |
| **Nekotina** (anime) | `/hug` `/pat` `/kiss` `/slap` `/cuddle` `/poke` `/bite` `/highfive` `/emote` | — |
| **FlaviBot** (eğlence) | `/8ball` `/roll` `/choose` `/poll` `/avatar` `/userinfo` `/serverinfo` | — |
| **VoiceMaster** | "Join to Create" kanalı; `/voice lock/unlock/limit/name/permit/reject/claim` | `/voice setup` |
| **Server Stat** | Üye/insan/bot/boost sayacı kanalları | `/stats setup` |
| **YouTube Alert** | Yeni videoda bildirim | `/youtube add` |
| **Double Counter** | Doğrulama: yeni hesap engeli + basit captcha | `/verify setup` |
| (yeni) | `/summary messages:10` → kanalın son 10 (veya `all`) mesajının İngilizce özeti | — |
| (önceki istek) | #general-english / #general-br'de @sawog/@admin etiketine "please open a ticket" cevabı | `.env` |

`/help` bütün komutları kategorilere göre listeler.

### `/summary`: sohbet özeti (yapay zekasız)
`/summary messages:10` (veya `25`, `100`, `all`; en fazla 1000) yazınca, sadece sana görünen bir özet gelir:
- Kaç mesaj, kaç kişi, kim ne kadar yazmış, hangi saat aralığı.
- **Konular:** çevrilmiş metinde en sık geçen kelimeler (örn. `map, game, freezes`).
- **Sorulan sorular:** "?" ile biten cümleler.
- **Konuşma:** Herkesin mesajı İngilizceye çevrilmiş halde. "ok, lol, kkkk, 👍" gibi boş mesajlar atlanır, aynı kişinin art arda mesajları tek satırda birleşir, botların mesajları gösterilmez.
- Konuşma tek mesaja sığmazsa en yeni kısım gösterilir, tamamı `.txt` olarak eklenir.

Seçenekler: `channel` (başka bir kanalı özetle), `language` (English / Türkçe / Português / Español). Sadece yetkililer kullanabilir.
Yapay zeka olmadığı için anlamı okuyup tek paragrafta özetleyemez; mesajları çevirip sadeleştirir.

### Dahil olmayanlar
- **Stupid Bot (genai):** yapay zeka gerektiriyor; yapay zekasız bot istediğin için eklenmedi.
- **Scriptly, sfw.bot, Circle:** sunucunda ne için kullandığını bilmiyorum. Söylersen eklerim.
- **Double Counter'ın IP ile alt hesap tespiti:** bir web sitesi ve kullanıcıların IP adreslerini toplamayı gerektiriyor. Yerine hesap yaşı kontrolü ve captcha var.
- **OwO'nun avlanma/hayvan sistemi:** sadece temel ekonomi var.

### Bilmen gerekenler
- **Müzik aynı anda tek ses kanalında çalar.** 3 ayrı Jockie botunun olmasının sebebi buydu: Discord'da bir bot, bir sunucuda aynı anda sadece bir ses kanalında olabilir. Aynı anda 2-3 kanalda müzik istiyorsan bu botun 2-3 kopyasını farklı token'larla çalıştırman gerekir.
- **Müzik YouTube'dan yt-dlp ile çalınır.** Bu YouTube'un kullanım şartlarına aykırıdır (Rythm bu yüzden kapanmıştı). Kendi sunucunda kullanmak senin kararın. YouTube sık değiştiği için `start.bat` her açılışta yt-dlp'yi günceller. Çalmazsa [Deno](https://deno.com) kur (`winget install DenoLand.Deno`); yt-dlp YouTube için buna ihtiyaç duyabiliyor.
- **Bot, bilgisayarın açık ve `start.bat` penceresi çalışır durumdayken çalışır.** Kapanırsa 5 saniye sonra kendini yeniden başlatır.
- Eski botları hemen atma. Önce bu botu kurup özellikleri tek tek dene, sonra eskileri çıkar.

## Kurulum

### 1. Discord'da botu oluştur
1. <https://discord.com/developers/applications> → **New Application** → **Bot** → **Reset Token** → token'ı kopyala.
2. Aynı sayfada **Privileged Gateway Intents** altında **SERVER MEMBERS INTENT** ve **MESSAGE CONTENT INTENT**'i aç.
3. **OAuth2 → URL Generator** → scope: `bot` + `applications.commands` → izin: **Administrator** (en kolayı). İstersen tek tek: Manage Roles, Manage Channels, Kick, Ban, Moderate Members, Manage Messages, Manage Server (davet takibi için), View Audit Log, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Connect, Speak, Move Members.
4. Linkle botu sunucuna ekle. **Sunucu Ayarları → Roller**'de botun rolünü en üste taşı (rol verebilmesi ve ceza verebilmesi için).

### 2. İndir ve çalıştır (Windows)
[Python 3.11+](https://www.python.org/downloads/) (kurulumda *Add python.exe to PATH* işaretli) ve [Git](https://git-scm.com/download/win) kur:

```bat
git clone -b claude/discord-bot-yazma-8n14jd https://github.com/sawog/pg3d.git
cd pg3d\discord-bot
copy .env.example .env
notepad .env
```

`.env` içine `DISCORD_TOKEN` ve `GUILD_ID` yaz. ID almak için: Discord → Ayarlar → Gelişmiş → **Geliştirici Modu** aç, sunucuya sağ tık → **ID'yi Kopyala**.
Sonra `start.bat`'a çift tıkla. FFmpeg dahil gereken her şey otomatik kurulur.

### 3. Discord'da ilk ayarlar (önerilen sıra)
```
/setup logs channel:#logs
/setup modlog channel:#mod-logs
/ticket setup channel:#support category:Tickets staff_role:@Staff log_channel:#ticket-logs
/welcome set channel:#welcome
/welcome autorole add role:@Member
/automod enable on:True
/automod word add words:kelime1, kelime2
/invites channel channel:#invite-logs
/levels channel channel:#level-up
/voice setup
/stats setup
/youtube add youtube_channel:@kanaladi channel:#videos
/verify setup channel:#verify role:@Verified
/roles panel channel:#roles title:Roller role1:@EN role2:@BR
/setup show
```

## Sonradan değiştirmek
- **Ayarlar:** Discord'daki komutlarla. Botu yeniden başlatmaya gerek yok.
- **`.env`:** Not Defteri ile düzenle, bot penceresini kapatıp `start.bat`'ı aç.
- **Güncelleme:** `pg3d` klasöründe `git pull` yaz, botu yeniden başlat. `.env` ve `bot.db` (ayarlar, seviyeler, paralar, uyarılar) silinmez.
