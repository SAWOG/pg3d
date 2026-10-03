# Discord Yardımcı Bot

Yapay zeka kullanmaz, API anahtarı ya da ücretli servis gerektirmez. Sadece Discord bot token'ı ve internet yeterli.

| Özellik | Nasıl çalışır |
|---|---|
| **Günlük öneri özeti** | Her gün `DAILY_SUMMARY_TIME` saatinde öneri kanalındaki son 24 saatin mesajlarını toplar, Türkçeye çevirir, birbirine benzeyen önerileri tek maddede birleştirir, 👍/👎 tepkilerine göre sıralar ve rapor kanalına atar (her maddede mesaja link var). `/oneri-ozet saat:48` ile istediğin an çalıştırabilirsin. |
| **Ticket özeti** | Yeni ticket açılınca `TICKET_AUTO_SUMMARY_DELAY` saniye bekler, sonra rapor kanalına atar: kim açtı, talebi (kullanıcının ilk mesajları, Türkçeye çevrilmiş), son mesajı, ekler, hangi yetkililer ilgilendi, durum (yanıtlanmadı / yetkili yanıtı bekleniyor / kullanıcı yanıtı bekleniyor). `/ticket-ozet` ile istediğin an da özetler. Ticket Tool vb. botlarla uyumlu: kategori ID'si ya da kanal adı önekiyle (`ticket-`) tanır. |
| **Kural uyarısı** | Her mesajı anında kontrol eder: yasaklı kelimeler (`banned_words.txt`), davet linki, izinsiz link, toplu etiket, spam (kısa sürede çok mesaj), aynı mesajı tekrar etme, tamamen büyük harf. İhlalde kullanıcıyı uyarır, mesajı siler, uyarıyı kaydeder, `WARN_TIMEOUT_THRESHOLD` uyarıda timeout atar ve log kanalına yazar. Düzenlenen mesajlar da kontrol edilir. Yetkililer, muaf roller ve ticket kanalları taranmaz. |

Komutların hepsi sadece **Mesajları Yönet** yetkisi olanlara görünür (ve sunucu tarafında tekrar kontrol edilir), yanıtlar sadece komutu kullanana görünür.

| Komut | Açıklama |
|---|---|
| `/oneri-ozet [saat]` | Öneri kanalını özetler (varsayılan 24 saat) |
| `/ticket-ozet [kanal]` | Ticket'ı özetler |
| `/uyarilar uye` | Üyenin aktif uyarıları |
| `/uyari-sil uye` | Üyenin uyarılarını sıfırlar |

## Kurulum

### 1. Discord botunu oluştur
1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** sekmesi → **Reset Token** → token'ı kopyala (kimseyle paylaşma).
3. Aynı sayfada **Privileged Gateway Intents** altında **MESSAGE CONTENT INTENT**'i aç.
4. **OAuth2 → URL Generator**: scope olarak `bot` + `applications.commands`; izinler:
   View Channels, Send Messages, Embed Links, Read Message History, Manage Messages, Moderate Members.
   Oluşan linkle botu sunucuna ekle.
5. Sunucuda botun rolünü, timeout atacağı üyelerin rollerinin **üstüne** taşı. Ticket kategorilerinde bota görme izni ver.

### 2. Kanal ID'leri
Discord → Ayarlar → Gelişmiş → **Geliştirici Modu**'nu aç. Kanala/kategoriye/sunucuya sağ tık → **ID'yi Kopyala**.

### 3. Çalıştır (Windows)
[Python 3.11+](https://www.python.org/downloads/) kur (kurulumda *Add python.exe to PATH* işaretli olsun).

```bat
cd discord-bot
copy .env.example .env
notepad .env
notepad banned_words.txt
start.bat
```

`start.bat` ilk çalıştırmada sanal ortamı ve paketleri kurar, sonra botu başlatır.

Linux/macOS:

```bash
cd discord-bot
cp .env.example .env   # doldur
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m bot
```

`GUILD_ID` doluysa slash komutları anında görünür; boşsa Discord'un global senkronu bir saati bulabilir.

## Ayarlar

Tüm ayarlar `.env` içinde, açıklamaları `.env.example`'da. Yasaklı kelimeler `banned_words.txt` dosyasında, her satıra bir tane. Büyük/küçük harf, Türkçe karakter (ş→s), leetspeak (4→a, 0→o) ve harf arasına boşluk koyma (`a p t a l`) otomatik yakalanır.

## Çeviri hakkında

Çeviri, Google Translate'in ücretsiz ve anahtarsız web adresiyle yapılır. Resmi bir API değildir: Google çok yoğun kullanımda geçici olarak engelleyebilir. Bu olursa bot durmaz, mesajları orijinal haliyle gösterir. Çeviriyi tamamen kapatmak için `.env`'de `TRANSLATE_ENABLED=false` yap.

## Güvenlik notları

- Komut yetkileri hem Discord tarafında hem botun kendi içinde kontrol edilir.
- `.env` ve `bot.db` `.gitignore`'da; token'ını commit'leme.
