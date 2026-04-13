import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scraper import collect_all, DATA_PATH
from analyzer import compute_stats

app = FastAPI(title="후기 대시보드")

# ── 정적 파일 (프론트엔드) ──
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── 스케줄러: 매일 새벽 1시 자동 수집 ──
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

@app.on_event("startup")
async def startup():
    scheduler.add_job(collect_all, "cron", hour=1, minute=0, id="daily_collect")
    scheduler.start()
    print("스케줄러 시작 (매일 01:00 KST 자동 수집)")

    # 데이터 파일이 없으면 최초 1회 수집
    if not DATA_PATH.exists():
        print("데이터 없음 → 최초 수집 시작...")
        await collect_all()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# ────────────────────────────────────────────
# API 엔드포인트
# ────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/data")
async def get_data():
    """저장된 리뷰 데이터 + 통계 반환"""
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail="데이터 수집 중입니다. 잠시 후 새로고침 해주세요.")

    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    changeok_reviews = raw["changeok"]["jasa"] + raw["changeok"]["smartstore"]
    myeongga_reviews = raw["myeongga"]["jasa"] + raw["myeongga"]["smartstore"]

    return {
        "last_updated": raw.get("last_updated"),
        "changeok": compute_stats(changeok_reviews),
        "myeongga": compute_stats(myeongga_reviews),
    }


@app.post("/api/collect")
async def trigger_collect(bg: BackgroundTasks):
    """수동 수집 트리거 (새로고침 버튼)"""
    bg.add_task(collect_all)
    return {"message": "수집을 시작했습니다. 5~10분 후 새로고침 해주세요."}


@app.get("/api/status")
async def status():
    exists = DATA_PATH.exists()
    last_updated = None
    if exists:
        with open(DATA_PATH, encoding="utf-8") as f:
            d = json.load(f)
        last_updated = d.get("last_updated")
    return {
        "data_exists": exists,
        "last_updated": last_updated,
        "next_scheduled": "매일 01:00 KST",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
