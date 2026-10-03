@echo off
cd /d "%~dp0"
if not exist venv (
    python -m venv venv || goto :error
    venv\Scripts\pip install -r requirements.txt || goto :error
)
venv\Scripts\python -m bot
pause
exit /b

:error
echo Kurulum basarisiz. Python 3.11+ kurulu ve PATH'te mi?
pause
