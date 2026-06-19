@echo off
chcp 65001 >nul
title 牌库 Bot 重启器
echo ================================
echo  牌库 Bot - 快速重启
echo ================================
echo.

echo [1/2] 正在停止旧进程...
taskkill /f /fi "WINDOWTITLE eq 牌库 Bot*" /t 2>nul
taskkill /f /im python.exe 2>nul
timeout /t 2 /nobreak >nul
cls

echo ================================
echo  牌库 Bot - 重启中...
echo ================================
echo.
start "牌库 Bot" "%~dp0start_bot.bat"
exit
