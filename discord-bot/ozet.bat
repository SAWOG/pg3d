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
    venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
)
chcp 65001 >nul
venv\Scripts\python -m bot.cli %*
exit /b

:error
echo Kurulum basarisiz. Python 3.11+ kurulu ve PATH'te mi?
pause
