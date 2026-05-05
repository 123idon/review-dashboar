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

# ── 수집 상태 (실시간 진행상황 포함) ──
collect_state = {
    "running": False,
    "last_success": None,
    "last_error": None,
    "error_detail": None,
    "phase": None,
    "brand": None,
    "page": 0,
    "total_so_far": 0,
    "done": 0,
    "total": 0,
    "collected": 0,
    "started_at": None,
    "live_logs": [],      # 실시간 로그 버퍼 (최근 200줄)
}


def progress_cb(info: dict):
    collect_state.update(info)
    # 진행 메시지를 실시간 로그에도 추가
    msg = info.get("progress_msg", "")
    if msg:
        _append_live_log(msg)


def _append_live_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    collect_state["live_logs"].append(f"[{ts}] {msg}")
    if len(collect_state["live_logs"]) > 200:
        collect_state["live_logs"] = collect_state["live_logs"][-200:]


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
        return
    collect_state.update({
        "running": True,
        "last_error": None,
        "error_detail": None,
        "phase": None,
        "brand": None,
        "page": 0,
        "total_so_far": 0,
        "done": 0,
        "total": 0,
        "collected": 0,
        "started_at": datetime.now().isoformat(),
        "live_logs": [],
    })
    _append_live_log("수집 시작")
    print(f"🔄 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        await collect_all(progress_cb=progress_cb)
        collect_state["last_success"] = datetime.now().isoformat()
        write_log(True, f"수집 완료 (총 {collect_state['collected']}건)")
        _append_live_log(f"✅ 수집 완료 (총 {collect_state['collected']}건)")
        print("✅ 수집 완료")
    except Exception as e:
        err = traceback.format_exc()
        collect_state["last_error"] = str(e)
        collect_state["error_detail"] = err
        write_log(False, str(e))
        _append_live_log(f"❌ 오류: {e}")
        print(f"❌ 수집 실패: {e}\n{err}")
    finally:
        collect_state["running"] = False


@app.on_event("startup")
async def startup():
    import asyncio
    scheduler.add_job(run_collect, "cron", hour=0, minute=6, id="daily")
    scheduler.start()

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
                print(f"📦 데이터 {age_hours:.0f}시간 경과 → 자동 수집")
                need_collect = True
        except Exception:
            need_collect = True

    if need_collect:
        asyncio.create_task(run_collect())

    print("✅ 서버 시작 완료")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/data")
async def get_data():
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail={
            "message": "수집 중입니다.",
            "collecting": collect_state["running"],
            "error": collect_state["last_error"],
        })
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": f"파일 오류: {e}"})

    changeok = raw["changeok"]["jasa"] + raw["changeok"]["smartstore"]
    myeongga = raw["myeongga"]["jasa"] + raw["myeongga"]["smartstore"]
    papa     = raw.get("papa", {}).get("jasa", []) + raw.get("papa", {}).get("smartstore", [])
    jasaol   = raw.get("jasaol", {}).get("jasa", []) + raw.get("jasaol", {}).get("smartstore", [])
    return {
        "last_updated": raw.get("last_updated"),
        "collecting": collect_state["running"],
        "changeok": compute_stats(changeok),
        "myeongga": compute_stats(myeongga),
        "papa":     compute_stats(papa),
        "jasaol":   compute_stats(jasaol),
    }


@app.get("/api/status")
async def get_status():
    s = collect_state.copy()

    # 진행률 계산
    pct = 0
    msg = ""
    elapsed = 0
    if s["started_at"]:
        elapsed = int((datetime.now() - datetime.fromisoformat(s["started_at"])).total_seconds())

    if s["running"]:
        brand = s.get("brand", "")
        done = s.get("done", 0)
        total = s.get("total", 1) or 1
        phase_pct = int(done / total * 100)

        # 브랜드별 전체 진행률 구간 (역행 방지)
        if brand == "명가삼대떡집":
            pct = int(phase_pct * 0.4)           # 0~40%
            msg = f"[명가삼대떡집] {done}/{total}배치 수집 중... ({pct}%)"
        elif brand == "파파공방":
            pct = 40 + int(phase_pct * 0.15)     # 40~55%
            msg = f"[파파공방] {done}/{total}상품 수집 중... ({pct}%)"
        elif brand == "자사몰":
            pct = 55 + int(phase_pct * 0.45)     # 55~100%
            msg = f"[자사몰] {done}/{total}상품 수집 중... ({pct}%)"
        elif s.get("phase") == "listing":
            pct = min(10, s.get("page", 0))
            msg = f"[{brand}] 목록 수집 중..."
        else:
            pct = 2
            msg = "수집 준비 중..."
        if s.get("progress_msg"):
            msg = s["progress_msg"]
    elif s["last_error"]:
        msg = f"오류: {s['last_error']}"
    elif s["last_success"]:
        msg = "수집 완료"

    return {
        "data_exists": DATA_PATH.exists(),
        "collecting": s["running"],
        "progress_pct": pct,
        "progress_msg": msg,
        "elapsed_sec": elapsed,
        "last_success": s["last_success"],
        "last_error": s["last_error"],
        "error_detail": s["error_detail"],
        "brand": s["brand"],
        "phase": s["phase"],
        "done": s["done"],
        "total": s["total"],
    }


@app.post("/api/collect")
async def trigger(bg: BackgroundTasks):
    if collect_state["running"]:
        return {"message": "이미 수집 중이에요."}
    bg.add_task(run_collect)
    return {"message": "수집 시작!"}


@app.get("/api/logs")
async def get_logs():
    if not LOG_PATH.exists():
        return {"logs": []}
    try:
        return {"logs": json.loads(LOG_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return {"logs": []}


@app.get("/api/live-logs")
async def get_live_logs(offset: int = 0):
    """실시간 수집 로그 - offset 이후 새 로그만 반환"""
    logs = collect_state["live_logs"]
    new_logs = logs[offset:] if offset < len(logs) else []
    return {
        "running": collect_state["running"],
        "logs": new_logs,
        "total": len(logs),
        "offset": offset,
    }


@app.get("/api/memo")
async def get_memo():
    if not MEMO_PATH.exists():
        return {"memos": []}
    try:
        data = json.loads(MEMO_PATH.read_text(encoding="utf-8"))
        return {"memos": []} if "content" in data else data
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
