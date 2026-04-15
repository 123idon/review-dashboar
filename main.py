import json
from datetime import datetime
import os
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

from scraper import collect_all, DATA_PATH
from analyzer import compute_stats

app = FastAPI()

Path("static").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

MEMO_PATH = Path("data/memo.json")

@app.on_event("startup")
async def startup():
    scheduler.add_job(collect_all, "cron", hour=0, minute=6, id="daily")
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
    return {"message": "수집 시작! 완료되면 자동으로 반영돼요."}

@app.get("/api/status")
async def status():
    return {"data_exists": DATA_PATH.exists()}

@app.get("/api/memo")
async def get_memo():
    if not MEMO_PATH.exists():
        return {"memos": []}
    with open(MEMO_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # 구버전 호환
    if "content" in data:
        return {"memos": []}
    return data

class MemoBody(BaseModel):
    content: str

@app.post("/api/memo")
async def save_memo(body: MemoBody):
    if not body.content.strip():
        return {"ok": False, "error": "내용을 입력해주세요"}
    memos = []
    if MEMO_PATH.exists():
        with open(MEMO_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if "memos" in data:
            memos = data["memos"]
    memos.insert(0, {
        "id": datetime.now().isoformat(),
        "content": body.content.strip(),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    with open(MEMO_PATH, "w", encoding="utf-8") as f:
        json.dump({"memos": memos}, f, ensure_ascii=False)
    return {"ok": True}

@app.delete("/api/memo/{memo_id}")
async def delete_memo(memo_id: str):
    if not MEMO_PATH.exists():
        return {"ok": False}
    with open(MEMO_PATH, encoding="utf-8") as f:
        data = json.load(f)
    memos = [m for m in data.get("memos", []) if m["id"] != memo_id]
    with open(MEMO_PATH, "w", encoding="utf-8") as f:
        json.dump({"memos": memos}, f, ensure_ascii=False)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
