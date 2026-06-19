@echo off
title 牌库 Bot
powershell -NoProfile -Command "while($true){Clear-Host;Write-Host '牌库 Bot 启动中...' -ForegroundColor Green;& 'C:\Users\Admin\.workbuddy\binaries\python\versions\3.13.12\python.exe' bot.py;Write-Host '';Write-Host 'Bot 停止, 3秒后重启...' -ForegroundColor Yellow;Start-Sleep 3}"
