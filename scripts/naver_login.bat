@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [백년화편] 네이버 판매자센터 로그인 후 서버로 세션 이전
set /p NAVER_CONNECT_TOKEN=서버 연결 토큰 입력: 
python naver_seller_local.py --login --push
pause
