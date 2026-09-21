@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [백년화편] 네이버 판매자센터 로그인 - 브라우저가 뜨면 직접 로그인하세요.
python naver_seller_local.py --login
pause
