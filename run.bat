@echo off
cd C:\Users\srtac\workspace\label-bot

echo Starting Label Bot...
start "LabelBot" python bot.py

echo Waiting for bot to start...
timeout /t 5 /nobreak > nul

echo Starting UI Server...
start "LabelServer" python server.py

echo Starting Ngrok Tunnel...
start "NgrokTunnel" ngrok http 5000 --domain=ronan-gibbed-latesha.ngrok-free.dev

echo Waiting for server to start...
timeout /t 10 /nobreak > nul

echo Opening UI in Chrome...
start chrome "C:\Users\srtac\workspace\label-bot\ui.html"

echo All services started!
