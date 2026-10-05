# Discord Yardımcı Bot

Yapay zeka kullanmaz, API anahtarı gerektirmez. Sadece Discord bot token'ı ve internet yeterli.

## 1. `/summary` — öneri paneli

`/summary kanal:#suggestions` yazınca sadece sana görünen bir panel açılır:

- Kanalda **henüz kabul ya da reddedilmemiş** bütün öneriler listelenir. Her önerinin yanında Türkçe kısa özeti, 👍/👎 oy sayısı, yazarı, tarihi ve mesaja link vardır.
- Listeden bir veya birden fazla öneriyi seçip:
  - **✅ Kabul et** ya da **❌ Reddet** → bir pencere açılır, açıklamayı yazarsın (opsiyonel). Bot öneri kanalında o mesaja cevap atar (yeşil "Suggestion accepted" / kırmızı "Suggestion rejected" + açıklama + kimin karar verdiği) ve mesaja ✅/❌ ekler.
  - **🙈 Cevapsız kapat** → kanala bir şey yazmadan listeden çıkarır (daha önce elle cevapladığın eski öneriler için).
- ◀️ ▶️ ile sayfa değiştirilir (sayfa başı 10 öneri), 🔄 ile liste yenilenir.
- Komut seçenekleri: `min_oy` (örn. sadece en az 5 oy almışlar), `siralama` (en çok oy / en yeni / en eski).

Karar verilen öneriler `bot.db` dosyasına kaydedilir, bir daha listelenmez. İki yetkili aynı öneriye aynı anda karar verirse sadece ilki uygulanır.

Öneri sayılmayanlar: botun kendi mesajları, önerilere yazılan yanıtlar (reply) ve sistem mesajları. Öneri botlarının embed'li mesajları da okunur.

## 2. Etiket uyarısı

Sadece **#general-english** ve **#general-br** kanallarında biri **@sawog** ya da **@admin** etiketlerse (gerçek etiket veya düz yazı), bot o mesaja her seferinde şu cevabı verir:

> Please open a ticket if you need something.

Yetkililer ve sawog'un kendisi muaf. Sadece "yanıtla" ile gelen otomatik ping uyarı tetiklemez, mesajın içinde etiket olmalı. Kanallar, isimler ve mesaj `.env` içinden değiştirilebilir.

## Kurulum

### 1. Discord botunu oluştur
1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** sekmesi → **Reset Token** → token'ı kopyala (kimseyle paylaşma).
3. Aynı sayfada **Privileged Gateway Intents** altında **MESSAGE CONTENT INTENT**'i aç.
4. **OAuth2 → URL Generator**: scope olarak `bot` + `applications.commands`; izinler:
   *View Channels, Send Messages, Embed Links, Read Message History, Add Reactions*.
   Oluşan linkle botu sunucuna ekle.

### 2. İndir
[Python 3.11+](https://www.python.org/downloads/) (kurulumda *Add python.exe to PATH* işaretli olsun) ve [Git for Windows](https://git-scm.com/download/win) kur. Komut isteminde:

```bat
git clone -b claude/discord-bot-yazma-8n14jd https://github.com/sawog/pg3d.git
cd pg3d\discord-bot
copy .env.example .env
notepad .env
```

`.env` içine en az `DISCORD_TOKEN` ve `GUILD_ID` yaz. Sunucu/kanal ID'si için: Discord → Ayarlar → Gelişmiş → **Geliştirici Modu** aç, sağ tık → **ID'yi Kopyala**.

### 3. Çalıştır
`start.bat`'a çift tıkla. İlk açılışta paketleri kendisi kurar. Pencere açık kaldığı sürece bot çalışır.

Linux/macOS:

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m bot
```

## Sonradan değiştirmek

- **Ayar** (kanal, mesaj metni, isimler): `.env`'yi Not Defteri ile düzenle → bot penceresini kapat → `start.bat`'ı tekrar aç. Yeniden indirmen gerekmez.
- **Kod güncellemesi:** `pg3d` klasöründe `git pull` → botu yeniden başlat. `.env` ve `bot.db` silinmez. `requirements.txt` değiştiyse `venv` klasörünü silip `start.bat`'ı aç.

## Çeviri hakkında

Çeviri, Google Translate'in ücretsiz ve anahtarsız web adresiyle yapılır; resmi bir API değildir. Çeviri başarısız olursa bot durmaz, öneriyi orijinal haliyle gösterir. Kapatmak için `TRANSLATE_ENABLED=false`.
