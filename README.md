# Railway 배포 수정 파일

## 완전 교체 파일 (그냥 덮어쓰기)
- Dockerfile
- railway.json  ← 새 파일
- requirements.txt

## 병합 필요 파일
### main.py
- 기존 코드는 유지하고:
  1. /health 엔드포인트 추가됨
  2. /api/status 엔드포인트 추가됨
  3. startup_event에 next_run_time=None 추가됨
  → 기존 리뷰 API, 메모 API 코드는 그대로 유지

### scraper.py
- 핵심 변경사항: playwright import를 파일 상단이 아닌 함수 안으로 이동
- browser.launch()에 args=['--no-sandbox', '--disable-dev-shm-usage'] 추가
- 기존 스크래핑 로직은 scrape_myungga(), scrape_changuk() 함수 안에 붙여넣기

### static/index.html
- 로딩 화면 추가됨
- 기존 스타일/HTML/렌더링 코드 주석 위치에 붙여넣기

## 배포 순서
1. 파일 교체
2. git add . && git commit -m "fix: Railway deployment" && git push
3. Railway → Settings → Deploy
   - Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
   - Health Check Path: /health
