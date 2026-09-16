@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행해 주세요.
  pause
  exit /b 1
)
py -3 -m venv .naver-setup
if errorlevel 1 goto fail
.naver-setup\Scripts\python.exe -m pip install playwright==1.55.0
if errorlevel 1 goto fail
.naver-setup\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto fail
.naver-setup\Scripts\python.exe connect_naver.py
exit /b %errorlevel%
:fail
echo 설치에 실패했습니다. 위 오류 메시지를 알려주세요.
pause
exit /b 1
