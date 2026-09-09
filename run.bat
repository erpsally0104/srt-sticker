@echo off
cd /d "%~dp0"

rem Windows consoles default to cp1252, which crashes on the status emoji
rem the moment anything prints one (check_printer.py, bot.py, server.py).
set PYTHONUTF8=1

echo Backing up database...
python backup_db.py

echo Starting Label Bot...
start "LabelBot" python bot.py

echo Waiting for bot to start...
timeout /t 5 /nobreak > nul

echo Starting UI Server...
start "LabelServer" python server.py

echo Starting Ngrok Tunnel...
start "NgrokTunnel" ngrok http 5000 --domain=canine-wrecker-mobile.ngrok-free.dev

echo Waiting for server to start...
timeout /t 10 /nobreak > nul

echo Opening UI in Chrome...
start chrome "%~dp0index.html"

echo All services started!
