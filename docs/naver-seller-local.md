# 네이버 후기 수집 (회사 PC · 판매자센터 세션 방식)

## 1. 최초 설치 (PowerShell, 1회)
```
pip install playwright openpyxl
python -m playwright install chromium
```

## 2. 로그인 (1회, 세션 만료 시 반복)
`naver_login.bat` 실행 → 브라우저에서 판매자센터에 직접 로그인 ('로그인 상태 유지' 체크)
→ 로그인 확인되면 창이 자동으로 닫히고 세션이 `%LOCALAPPDATA%\review_dashboard\naver_profile` 에 저장됨.

## 3. 매일 자동 실행 (작업 스케줄러)
- 트리거: 매일 09:00
- 동작: 프로그램 시작 → `run_naver_seller.bat` (시작 위치: 스크립트 폴더)
- "사용자가 로그온되어 있을 때만 실행" 으로 두는 것이 안전 (창 있는 브라우저 사용)

또는 PowerShell 한 줄로 등록:
```
schtasks /Create /SC DAILY /ST 09:00 /TN "BNH_NaverReview" /TR "\"%CD%\run_naver_seller.bat\"" /F
```

## 4. 동작 흐름
1. 대시보드 서버에서 마지막 후기 날짜 조회 → 7일 전부터 재조회 (중복은 서버가 제거)
2. 판매자센터 리뷰관리 화면 읽기
3. 실패 시 같은 화면에서 엑셀 다운로드 → 파싱 (폴백)
4. 서버 업로드 → 병합 → 대시보드 반영
5. 세션 만료면 대시보드에 빨간 배너 → `naver_login.bat` 다시 실행

## 5. 로그 / 결과
- `%LOCALAPPDATA%\review_dashboard\naver_seller_local.log`
- `%LOCALAPPDATA%\review_dashboard\last_result.json`
- 종료 코드: 0 성공 / 1 수집 오류 / 2 로그인 필요

## 옵션
- `--since 2026-09-01` 특정 날짜부터 다시 수집
- `--overlap-days 14` 재조회 범위 조정
- `--headless` 창 없이 실행 (권장하지 않음)
