@echo off
chcp 65001 >nul
cd /d "%~dp0"
python naver_seller_local.py
exit /b %ERRORLEVEL%
