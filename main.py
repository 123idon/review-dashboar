import json
import traceback
from datetime import datetime
import os
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse
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
    entry = f"[{ts}] {msg}"
    # 마지막 로그와 메시지가 같으면 추가 안 함 (중복 방지)
    logs = collect_state["live_logs"]
    if logs and "] " in logs[-1] and logs[-1].split("] ", 1)[-1] == msg:
        return
    logs.append(entry)
    if len(logs) > 200:
        collect_state["live_logs"] = logs[-200:]


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

    from scraper import JASAOL_BASE_PATH, JASAOL_NEW_PATH, load_json
    SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"
    changeok = raw.get("changeok", {}).get("jasa", []) + raw.get("changeok", {}).get("smartstore", [])
    myeongga = raw.get("myeongga", {}).get("jasa", []) + raw.get("myeongga", {}).get("smartstore", [])
    papa     = raw.get("papa", {}).get("jasa", []) + raw.get("papa", {}).get("smartstore", [])
    # jasaol: base(XLS) + new(증분) 합산
    jasaol_base = load_json(JASAOL_BASE_PATH, [])
    jasaol_new  = load_json(JASAOL_NEW_PATH, [])
    jasaol = jasaol_base + jasaol_new
    del jasaol_base, jasaol_new
    # smartstore: 집 PC에서 수집한 네이버 리뷰
    smartstore = load_json(SMARTSTORE_PATH, [])
    return {
        "last_updated": raw.get("last_updated"),
        "collecting": collect_state["running"],
        "changeok":   compute_stats(changeok),
        "myeongga":   compute_stats(myeongga),
        "papa":       compute_stats(papa),
        "jasaol":     compute_stats(jasaol),
        "smartstore": compute_stats(smartstore),
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


@app.post("/api/import-smartstore-chunk")
async def import_smartstore_chunk(request: Request):
    """집 PC에서 수집한 네이버 리뷰 청크 수신"""
    try:
        body = await request.json()
        reviews = body.get("reviews", [])
        replace = body.get("replace", False)
        CHUNK_PATH = DATA_PATH.parent / "smartstore_chunk.json"
        if replace:
            chunk_data = reviews
        else:
            existing = []
            if CHUNK_PATH.exists():
                try:
                    existing = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            chunk_data = existing + reviews
        CHUNK_PATH.write_text(json.dumps(chunk_data, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "total": len(chunk_data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import-smartstore-done")
async def import_smartstore_done():
    """네이버 리뷰 청크 완료 → smartstore.json에 저장"""
    try:
        CHUNK_PATH = DATA_PATH.parent / "smartstore_chunk.json"
        if not CHUNK_PATH.exists():
            raise HTTPException(status_code=400, detail="청크 없음")
        from scraper import safe_save, load_json
        SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"
        reviews = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
        safe_save(SMARTSTORE_PATH, reviews)
        CHUNK_PATH.unlink(missing_ok=True)
        # last_updated 갱신
        data = load_json(DATA_PATH, {})
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        return {"ok": True, "imported": len(reviews)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
async def import_jasaol_chunk(request: Request):
    """브라우저에서 파싱한 리뷰 청크를 받아서 저장"""
    try:
        body = await request.json()
        reviews = body.get("reviews", [])
        replace = body.get("replace", False)  # True면 기존 교체, False면 추가

        CHUNK_PATH = DATA_PATH.parent / "jasaol_chunk.json"

        if replace:
            # 첫 청크: 새로 시작
            chunk_data = reviews
        else:
            # 이후 청크: 기존에 추가
            existing_chunk = []
            if CHUNK_PATH.exists():
                try:
                    existing_chunk = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
                except Exception:
                    existing_chunk = []
            chunk_data = existing_chunk + reviews

        CHUNK_PATH.write_text(json.dumps(chunk_data, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "total": len(chunk_data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import-jasaol-done")
async def import_jasaol_done():
    """청크 수집 완료 - jasaol_base.json에 반영"""
    try:
        CHUNK_PATH = DATA_PATH.parent / "jasaol_chunk.json"
        if not CHUNK_PATH.exists():
            raise HTTPException(status_code=400, detail="청크 데이터 없음")

        from scraper import JASAOL_BASE_PATH, JASAOL_NEW_PATH, safe_save as sc_save
        reviews = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))

        # base에 저장 (XLS 전체 데이터)
        sc_save(JASAOL_BASE_PATH, reviews)
        # new는 초기화 (base가 최신이므로)
        sc_save(JASAOL_NEW_PATH, [])
        CHUNK_PATH.unlink(missing_ok=True)

        # reviews.json last_updated 갱신
        data = {}
        if DATA_PATH.exists():
            try:
                data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        data.setdefault("changeok", {"jasa": [], "smartstore": []})
        data.setdefault("myeongga", {"jasa": [], "smartstore": []})
        data.setdefault("papa",     {"jasa": [], "smartstore": []})
        data["last_updated"] = datetime.now().isoformat()
        sc_save(DATA_PATH, data)

        return {"ok": True, "imported": len(reviews)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
