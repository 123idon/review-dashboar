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
app.mount("/static", StaticFiles(directory="static"), name="static")

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

@app.on_event("startup")
async def startup():
    scheduler.add_job(collect_all, "cron", hour=1, minute=0, id="daily_collect")
    # 시작 후 30초 뒤에 첫 수집 (앱 응답 먼저 확보)
    if not DATA_PATH.exists():
        scheduler.add_job(collect_all, "date", 
                         run_date=datetime.now().replace(second=datetime.now().second + 30),
                         id="first_collect")
    scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/api/data")
async def get_data():
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
    return {"data_exists": exists, "last_updated": last_updated}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
