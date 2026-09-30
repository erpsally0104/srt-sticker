@echo off
cd /d "%~dp0"

rem Windows consoles default to cp1252, which crashes on the status emoji
rem the moment anything prints one (check_printer.py, bot.py, server.py).
set PYTHONUTF8=1

echo Backing up database...
python backup_db.py

rem cmd /k keeps each window open after python exits, so a crash on startup
rem leaves its error on screen. Plain "start python" closed the window and
rem the only sign was ngrok answering 502 for every request.
echo Starting Label Bot...
start "LabelBot" cmd /k python bot.py

echo Waiting for bot to start...
timeout /t 5 /nobreak > nul

echo Starting UI Server...
start "LabelServer" cmd /k python server.py

echo Starting Ngrok Tunnel...
start "NgrokTunnel" ngrok http 5000 --domain=canine-wrecker-mobile.ngrok-free.dev

echo Waiting for server to start...
timeout /t 10 /nobreak > nul

echo Opening UI in Chrome...
start chrome "%~dp0index.html"

echo All services started!
