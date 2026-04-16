import json
import traceback
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
LOG_PATH  = Path("data/collect_log.json")

# ── 수집 상태 ──
collect_state = {
    "running": False,
    "last_success": None,
    "last_error": None,
    "error_detail": None,
}


def write_log(success: bool, detail: str = ""):
    logs = []
    if LOG_PATH.exists():
        try:
            logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logs = []
    logs.insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "success": success,
        "detail": detail,
    })
    LOG_PATH.write_text(json.dumps(logs[:50], ensure_ascii=False), encoding="utf-8")


async def run_collect():
    if collect_state["running"]:
        print("⚠️ 이미 수집 중 - 중복 실행 방지")
        return
    collect_state["running"] = True
    collect_state["last_error"] = None
    collect_state["error_detail"] = None
    print(f"🔄 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        await collect_all()
        collect_state["last_success"] = datetime.now().isoformat()
        write_log(True, "수집 완료")
        print("✅ 수집 완료")
    except Exception as e:
        err = traceback.format_exc()
        collect_state["last_error"] = str(e)
        collect_state["error_detail"] = err
        write_log(False, str(e))
        print(f"❌ 수집 실패: {e}\n{err}")
    finally:
        collect_state["running"] = False


@app.on_event("startup")
async def startup():
    import asyncio

    # 매일 새벽 0:06 자동 수집
    scheduler.add_job(run_collect, "cron", hour=0, minute=6, id="daily")
    scheduler.start()

    # 데이터 없거나 하루 이상 오래됐으면 자동 수집
    need_collect = False
    if not DATA_PATH.exists():
        print("📦 데이터 없음 → 자동 수집 시작")
        need_collect = True
    else:
        try:
            raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(raw.get("last_updated", "2000-01-01"))
            age_hours = (datetime.now() - last).total_seconds() / 3600
            if age_hours > 23:
                print(f"📦 데이터가 {age_hours:.0f}시간 경과 → 자동 수집 시작")
                need_collect = True
        except Exception:
            need_collect = True

    if need_collect:
        asyncio.create_task(run_collect())

    print("✅ 서버 시작 완료")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# ── 헬스체크 ──
@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 메인 페이지 ──
@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ── 데이터 API ──
@app.get("/api/data")
async def get_data():
    if not DATA_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "아직 데이터가 없어요. 수집 중입니다.",
                "collecting": collect_state["running"],
                "error": collect_state["last_error"],
            }
        )
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": f"데이터 파일 오류: {e}"})

    changeok = raw["changeok"]["jasa"] + raw["changeok"]["smartstore"]
    myeongga = raw["myeongga"]["jasa"] + raw["myeongga"]["smartstore"]
    return {
        "last_updated": raw.get("last_updated"),
        "collecting": collect_state["running"],
        "changeok": compute_stats(changeok),
        "myeongga": compute_stats(myeongga),
    }


# ── 수집 상태 API ──
@app.get("/api/status")
async def get_status():
    return {
        "data_exists": DATA_PATH.exists(),
        "collecting": collect_state["running"],
        "last_success": collect_state["last_success"],
        "last_error": collect_state["last_error"],
        "error_detail": collect_state["error_detail"],
    }


# ── 수동 수집 트리거 ──
@app.post("/api/collect")
async def trigger(bg: BackgroundTasks):
    if collect_state["running"]:
        return {"message": "이미 수집 중이에요."}
    bg.add_task(run_collect)
    return {"message": "수집 시작! 완료되면 자동으로 반영돼요."}


# ── 수집 로그 API ──
@app.get("/api/logs")
async def get_logs():
    if not LOG_PATH.exists():
        return {"logs": []}
    try:
        return {"logs": json.loads(LOG_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return {"logs": []}


# ── 메모 API ──
@app.get("/api/memo")
async def get_memo():
    if not MEMO_PATH.exists():
        return {"memos": []}
    try:
        data = json.loads(MEMO_PATH.read_text(encoding="utf-8"))
        if "content" in data:
            return {"memos": []}
        return data
    except Exception:
        return {"memos": []}


class MemoBody(BaseModel):
    content: str


@app.post("/api/memo")
async def save_memo(body: MemoBody):
    if not body.content.strip():
        return {"ok": False, "error": "내용을 입력해주세요"}
    memos = []
    if MEMO_PATH.exists():
        try:
            data = json.loads(MEMO_PATH.read_text(encoding="utf-8"))
            if "memos" in data:
                memos = data["memos"]
        except Exception:
            pass
    memos.insert(0, {
        "id": datetime.now().isoformat(),
        "content": body.content.strip(),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    MEMO_PATH.write_text(json.dumps({"memos": memos}, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@app.delete("/api/memo/{memo_id}")
async def delete_memo(memo_id: str):
    if not MEMO_PATH.exists():
        return {"ok": False}
    try:
        data = json.loads(MEMO_PATH.read_text(encoding="utf-8"))
        memos = [m for m in data.get("memos", []) if m["id"] != memo_id]
        MEMO_PATH.write_text(json.dumps({"memos": memos}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
