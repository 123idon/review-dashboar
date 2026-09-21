@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title 백년화편 네이버 후기 수집 - 설치 및 실행

set "PYVER=3.12.10"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "SCRIPT_URL=https://raw.githubusercontent.com/123idon/review-dashboar/main/scripts/naver_seller_local.py"
set "WORK=%USERPROFILE%\review_dashboard"
set "PYEXE="

echo ==========================================================
echo   백년화편 네이버 후기 수집기 - 자동 설치 및 실행
echo   (파이썬이 없으면 설치하고, 필요한 것 전부 자동으로 준비합니다)
echo ==========================================================
echo.
if not exist "%WORK%" mkdir "%WORK%"
cd /d "%WORK%"

:: ---------- 1. 파이썬 확인 ----------
echo [1/5] 파이썬 확인 중...
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe") do (
    if not defined PYEXE if exist %%P set "PYEXE=%%~P"
)
if not defined PYEXE (
    for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PYEXE set "PYEXE=%%I"
)
if defined PYEXE (
    echo      기존 파이썬 사용: !PYEXE!
    goto :PKG
)

:: ---------- 2. 파이썬 설치 ----------
echo      파이썬이 없습니다. 설치 파일을 내려받습니다 (약 25MB)...
curl -L -# -o "%TEMP%\python-installer.exe" "%PYURL%"
if not exist "%TEMP%\python-installer.exe" (
    echo      curl 실패 - PowerShell 로 다시 시도합니다...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%PYURL%' -OutFile '%TEMP%\python-installer.exe'"
)
if not exist "%TEMP%\python-installer.exe" (
    echo      [오류] 파이썬 설치 파일을 내려받지 못했습니다. 인터넷 연결을 확인하세요.
    goto :FAIL
)
echo      파이썬 %PYVER% 설치 중 (1~2분, 관리자 권한 불필요)...
"%TEMP%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Include_pip=1
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "!PYEXE!" (
    echo      [오류] 파이썬 설치가 완료되지 않았습니다.
    goto :FAIL
)
echo      설치 완료: !PYEXE!

:PKG
:: ---------- 3. 패키지 + 크로미움 ----------
echo.
echo [2/5] 필요한 패키지 설치 (playwright, openpyxl)...
"!PYEXE!" -m pip install --quiet --upgrade pip >nul 2>&1
"!PYEXE!" -m pip install --quiet playwright openpyxl
if errorlevel 1 (
    echo      [오류] 패키지 설치 실패
    goto :FAIL
)
echo [3/5] 브라우저(크로미움) 준비 - 약 150MB, 처음 한 번만 오래 걸립니다...
"!PYEXE!" -m playwright install chromium
if errorlevel 1 (
    echo      [오류] 크로미움 설치 실패
    goto :FAIL
)

:: ---------- 4. 수집 스크립트 최신본 ----------
echo.
echo [4/5] 수집 스크립트 최신본 내려받기...
curl -L -s -o "naver_seller_local.py" "%SCRIPT_URL%"
if not exist "naver_seller_local.py" (
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%SCRIPT_URL%' -OutFile 'naver_seller_local.py'"
)
if not exist "naver_seller_local.py" (
    echo      [오류] 스크립트를 내려받지 못했습니다.
    goto :FAIL
)

:: ---------- 5. 로그인 + 서버로 세션 이전 ----------
echo.
echo [5/5] 이제 브라우저가 열립니다. 판매자센터에 직접 로그인하세요.
echo       ("로그인 상태 유지" 체크 권장. 로그인이 확인되면 창이 자동으로 닫히고
echo        세션이 서버로 넘어가 이후에는 서버가 매일 자동 수집합니다.)
echo.
set /p NAVER_CONNECT_TOKEN=서버 연결 토큰을 붙여넣고 Enter: 
if "%NAVER_CONNECT_TOKEN%"=="" (
    echo      토큰이 비어 있어 로그인만 저장하고 서버 이전은 건너뜁니다.
    "!PYEXE!" naver_seller_local.py --login
) else (
    "!PYEXE!" naver_seller_local.py --login --push
)
if errorlevel 1 (
    echo.
    echo      [주의] 로그인/이전이 완료되지 않았습니다. 위 메시지를 확인하세요.
    echo      로그: %LOCALAPPDATA%\review_dashboard\naver_seller_local.log
    goto :FAIL
)
echo.
echo ==========================================================
echo   완료. 이제 이 PC를 꺼도 서버가 매일 00:00 자동 수집합니다.
echo   세션이 만료되면 대시보드에 빨간 배너가 뜨고, 그때 이 파일을 다시 실행하면 됩니다.
echo ==========================================================
pause
exit /b 0

:FAIL
echo.
echo 실패했습니다. 이 창을 캡처해서 보내주세요.
pause
exit /b 1
