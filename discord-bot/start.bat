@echo off
cd /d "%~dp0"
if not exist .env (
    copy .env.example .env >nul
    echo .env dosyasi olusturuldu. Acilan Not Defteri'nde DISCORD_TOKEN ve GUILD_ID'yi yaz, kaydet ve kapat.
    start /wait notepad .env
)
if not exist venv (
    echo Ilk kurulum yapiliyor, birkac dakika surebilir...
    python -m venv venv || goto :error
)
venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
rem YouTube sik degistigi icin muzik kutuphanesi her acilista guncellenir
venv\Scripts\python -m pip install -q -U yt-dlp

:run
venv\Scripts\python -m bot
echo.
echo Bot kapandi. 5 saniye sonra yeniden baslatilacak (kapatmak icin pencereyi kapat).
timeout /t 5 >nul
goto run

:error
echo Kurulum basarisiz. Python 3.11+ kurulu ve PATH'te mi?
pause
