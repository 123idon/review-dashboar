# 후기 대시보드 설치 가이드

## 파일 구조
```
review_dashboard/
├── main.py           # FastAPI 서버
├── scraper.py        # 후기 수집 (Cafe24 + 네이버)
├── analyzer.py       # 통계 / 키워드 분석
├── requirements.txt
├── Procfile          # Railway 배포용
├── static/
│   └── index.html    # 대시보드 화면
└── data/
    └── reviews.json  # 수집된 데이터 (자동 생성)
```

---

## 1단계 — GitHub에 올리기

1. https://github.com 접속 → 로그인
2. 오른쪽 상단 **+** → **New repository**
3. Repository name: `review-dashboard` → **Create repository**
4. 로컬 PC에서 아래 실행:

```bash
cd review_dashboard
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_ID/review-dashboard.git
git push -u origin main
```

---

## 2단계 — Railway 배포

1. https://railway.app 접속 → **GitHub으로 로그인**
2. **New Project** → **Deploy from GitHub repo**
3. `review-dashboard` 선택
4. 자동으로 빌드 시작 (3~5분)
5. 완료되면 **Settings** → **Domains** → **Generate Domain** 클릭
6. 생성된 주소 (예: `https://review-dashboard-xxx.railway.app`) 북마크

---

## 3단계 — 첫 실행

- 배포 직후 서버가 뜨면 **자동으로 후기 수집을 시작**합니다
- 처음 수집은 5~15분 소요
- 완료 후 위 주소를 열면 대시보드가 표시됩니다
- 이후 **매일 새벽 1시**에 자동 수집

---

## 수동 새로고침

대시보드 상단 **새로고침** 버튼 클릭 → 즉시 수집 시작
(완료까지 5~10분 후 브라우저 새로고침)

---

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 화면이 안 뜸 | 첫 수집 중 | 10분 후 다시 접속 |
| 스마트스토어 0건 | 네이버 구조 변경 | scraper.py Playwright 셀렉터 수정 필요 |
| 자사몰 별점 0점 | Cafe24 스킨 차이 | scraper.py 셀렉터 확인 |
| Railway 빌드 실패 | Playwright 설치 오류 | Railway 지원팀 문의 또는 Dockerfile 방식 전환 |
