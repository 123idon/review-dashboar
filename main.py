import json
import os
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scraper import collect_all, DATA_PATH
from analyzer import compute_stats

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

@app.on_event("startup")
async def startup():
    scheduler.add_job(collect_all, "cron", hour=1, minute=0, id="daily")
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
        raise HTTPException(status_code=503, detail="아직 데이터가 없어요. 상단 새로고침 버튼을 눌러주세요.")
    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    changeok = raw["changeok"]["jasa"] + raw["changeok"]["smartstore"]
    myeongga = raw["myeongga"]["jasa"] + raw["myeongga"]["smartstore"]
    return {
        "last_updated": raw.get("last_updated"),
        "changeok": compute_stats(changeok),
        "myeongga": compute_stats(myeongga),
    }

@app.post("/api/collect")
async def trigger(bg: BackgroundTasks):
    bg.add_task(collect_all)
    return {"message": "수집 시작! 5~10분 후 새로고침 해주세요."}

@app.get("/api/status")
async def status():
    return {"data_exists": DATA_PATH.exists()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
