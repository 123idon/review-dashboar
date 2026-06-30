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
from analyzer import compute_stats, get_reviews_page
import survey_module

# ── 리뷰 데이터 메모리 캐시 ──
_reviews_cache = None   # {'jasaol': [...], 'myeongga': [...], ...}
_cache_mtime = {}       # 파일별 수정 시각

def _get_mtime(path):
    try: return path.stat().st_mtime
    except: return 0

def _load_reviews_cached():
    """파일 변경 시에만 재로드, 아니면 캐시 반환"""
    global _reviews_cache, _cache_mtime
    from scraper import JASAOL_BASE_PATH, JASAOL_NEW_PATH, load_json
    SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"

    paths = {
        'reviews': DATA_PATH,
        'jasaol_base': JASAOL_BASE_PATH,
        'jasaol_new': JASAOL_NEW_PATH,
        'smartstore': SMARTSTORE_PATH,
    }
    mtimes = {k: _get_mtime(v) for k, v in paths.items()}

    if _reviews_cache is not None and mtimes == _cache_mtime:
        return _reviews_cache  # 캐시 히트

    # 캐시 미스 → 파일 로드
    try:
        raw = load_json(DATA_PATH, {})
        changeok = raw.get("changeok", {}).get("jasa", []) + raw.get("changeok", {}).get("smartstore", [])
        myeongga = raw.get("myeongga", {}).get("jasa", []) + raw.get("myeongga", {}).get("smartstore", [])
        papa     = raw.get("papa", {}).get("jasa", []) + raw.get("papa", {}).get("smartstore", [])
        jasaol_base = load_json(JASAOL_BASE_PATH, [])
        jasaol_new  = load_json(JASAOL_NEW_PATH, [])
        smartstore  = load_json(SMARTSTORE_PATH, [])
        # 중복 제거: (author, date, content) 기준 — jasaol+smartstore 전체 중복 제거
        seen_keys = set()
        jasaol_all = []
        for rv in jasaol_base + jasaol_new + smartstore:
            key = (rv.get("author",""), rv.get("date",""), rv.get("content","")[:100])
            if key not in seen_keys:
                seen_keys.add(key)
                jasaol_all.append(rv)
        jasaol = jasaol_all

        _reviews_cache = {
            'raw_last_updated': raw.get("last_updated"),
            'changeok':   changeok,
            'myeongga':   myeongga,
            'papa':       papa,
            'jasaol':     jasaol,
            'smartstore': smartstore,
        }
        _cache_mtime = mtimes
    except Exception as e:
        print(f"캐시 로드 실패: {e}")
    return _reviews_cache

def invalidate_cache():
    """수집/임포트 완료 후 캐시 무효화"""
    global _reviews_cache, _cache_mtime
    _reviews_cache = None
    _cache_mtime = {}

app = FastAPI()
Path("static").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

MEMO_PATH = Path("data/memo.json")
LOG_PATH = Path("data/collect_log.json")

collect_state = {
    "running": False, "last_success": None, "last_error": None,
    "error_detail": None, "phase": None, "brand": None, "page": 0,
    "total_so_far": 0, "done": 0, "total": 0, "collected": 0,
    "started_at": None, "live_logs": [],
}

survey_state = {
    "running": False, "last_success": None, "last_error": None, "count": 0,
}

async def run_survey_collect():
    """구글 서비스 계정으로 설문 시트를 수집해 data/survey.json 저장."""
    import asyncio
    if survey_state["running"]:
        return
    survey_state["running"] = True
    survey_state["last_error"] = None
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, survey_module.collect_survey)
        survey_state["last_success"] = result["last_updated"]
        survey_state["count"] = result["count"]
        print(f"📋 설문 수집 완료: {result['count']}건")
    except Exception as e:
        survey_state["last_error"] = str(e)
        print(f"❌ 설문 수집 실패: {e}")
    finally:
        survey_state["running"] = False

def progress_cb(info: dict):
    collect_state.update(info)
    msg = info.get("progress_msg", "")
    if msg:
        _append_live_log(msg)

def _append_live_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
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
        "running": True, "last_error": None, "error_detail": None,
        "phase": None, "brand": None, "page": 0, "total_so_far": 0,
        "done": 0, "total": 0, "collected": 0,
        "started_at": datetime.now().isoformat(), "live_logs": [],
    })
    _append_live_log("수집 시작")
    print(f"🔄 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        await collect_all(progress_cb=progress_cb)
        collect_state["last_success"] = datetime.now().isoformat()
        invalidate_cache()  # 수집 완료 → 캐시 무효화
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
    scheduler.add_job(run_survey_collect, "cron", hour=0, minute=20, id="survey_daily")
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
    # 설문: 서비스 계정 키가 있고 데이터가 없으면 1회 수집
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and not survey_module.SURVEY_PATH.exists():
        print("📋 설문 데이터 없음 → 자동 수집 시도")
        asyncio.create_task(run_survey_collect())
    print("✅ 서버 시작 완료")

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.post("/api/cleanup-jasaol-new")
async def cleanup_jasaol_new():
    """jasaol_new.json 중복 제거 및 이상 데이터 정리"""
    from scraper import JASAOL_NEW_PATH, load_json, safe_save
    data = load_json(JASAOL_NEW_PATH, [])
    before = len(data)
    seen = set()
    cleaned = []
    for rv in data:
        # (날짜+작성자+내용) 기준 - 같은 사람이 같은날 같은 내용을 여러상품에 쓴 경우 1건만
        key = (rv.get("date",""), rv.get("author",""), rv.get("content","")[:80])
        if key not in seen:
            seen.add(key)
            cleaned.append(rv)
    safe_save(JASAOL_NEW_PATH, cleaned)
    invalidate_cache()
    return {"before": before, "after": len(cleaned), "removed": before - len(cleaned)}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return FileResponse("static/landing.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/index.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})
@app.get("/insights")
async def insights():
    return FileResponse("static/insights.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/memo")
async def memo_page():
    return FileResponse("static/memo.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/changelog")
async def changelog_page():
    return FileResponse("static/changelog.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/api/reports")
async def list_reports():
    """static/reports/ 폴더의 HTML 리포트 목록 반환"""
    reports_dir = Path("static/reports")
    reports_dir.mkdir(exist_ok=True)
    files = []
    for f in sorted(reports_dir.glob("*.html"), reverse=True):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "url": f"/static/reports/{f.name}",
            "size": stat.st_size,
            "modified": stat.st_mtime
        })
    return JSONResponse({"reports": files})


@app.get("/api/data")
async def get_data(date_from: str = None, date_to: str = None):
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail={
            "message": "수집 중입니다.",
            "collecting": collect_state["running"],
            "error": collect_state["last_error"],
        })
    import asyncio
    cache = await asyncio.get_event_loop().run_in_executor(None, _load_reviews_cached)
    if not cache:
        raise HTTPException(status_code=500, detail={"message": "데이터 로드 실패"})
    return {
        "last_updated": cache['raw_last_updated'],
        "collecting": collect_state["running"],
        "changeok":   compute_stats(cache['changeok'],   date_from, date_to),
        "myeongga":   compute_stats(cache['myeongga'],   date_from, date_to),
        "papa":       compute_stats(cache['papa'],       date_from, date_to),
        "jasaol":     compute_stats(cache['jasaol'],     date_from, date_to),
        "smartstore": compute_stats(cache['smartstore'], date_from, date_to),
    }

@app.get("/api/status")
async def get_status():
    s = collect_state.copy()
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
        if brand == "명가삼대떡집":
            pct = int(phase_pct * 0.4)
            msg = f"[명가삼대떡집] {done}/{total}배치 수집 중... ({pct}%)"
        elif brand == "파파공방":
            pct = 40 + int(phase_pct * 0.15)
            msg = f"[파파공방] {done}/{total}상품 수집 중... ({pct}%)"
        elif brand == "자사몰":
            pct = 55 + int(phase_pct * 0.45)
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
    logs = collect_state["live_logs"]
    new_logs = logs[offset:] if offset < len(logs) else []
    return {
        "running": collect_state["running"],
        "logs": new_logs,
        "total": len(logs),
        "offset": offset,
    }


@app.get("/api/reviews")
async def get_reviews(
    shop: str = "jasaol",
    page: int = 1,
    size: int = 20,
    filter_type: str = "all",
    date_from: str = None,
    date_to: str = None,
):
    """후기 목록 페이지네이션 전용 API"""
    import asyncio
    cache = await asyncio.get_event_loop().run_in_executor(None, _load_reviews_cached)
    if not cache:
        raise HTTPException(status_code=500, detail="데이터 로드 실패")
    reviews = cache.get(shop, [])
    result = get_reviews_page(
        reviews,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
        filter_type=filter_type,
    )
    return result

@app.get("/api/smartstore-latest-date")
async def smartstore_latest_date():
    from scraper import load_json
    SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"
    reviews = load_json(SMARTSTORE_PATH, [])
    if not reviews:
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return {"date": yesterday}
    dates = [r["date"] for r in reviews if r.get("date")]
    return {"date": max(dates) if dates else datetime.now().strftime("%Y-%m-%d")}

SMARTSTORE_STATUS = {"cookie_expired": False, "expired_at": None}

@app.post("/api/smartstore-cookie-expired")
async def smartstore_cookie_expired(request: Request):
    body = await request.json()
    SMARTSTORE_STATUS["cookie_expired"] = True
    SMARTSTORE_STATUS["expired_at"] = body.get("expired_at")
    return {"ok": True}

@app.get("/api/smartstore-status")
async def smartstore_status():
    return SMARTSTORE_STATUS

@app.post("/api/smartstore-cookie-ok")
async def smartstore_cookie_ok():
    SMARTSTORE_STATUS["cookie_expired"] = False
    SMARTSTORE_STATUS["expired_at"] = None
    return {"ok": True}

@app.post("/api/import-smartstore-chunk")
async def import_smartstore_chunk(request: Request):
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
    try:
        CHUNK_PATH = DATA_PATH.parent / "smartstore_chunk.json"
        if not CHUNK_PATH.exists():
            raise HTTPException(status_code=400, detail="청크 없음")
        from scraper import safe_save, load_json
        SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"
        reviews = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
        safe_save(SMARTSTORE_PATH, reviews)
        CHUNK_PATH.unlink(missing_ok=True)
        data = load_json(DATA_PATH, {})
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        invalidate_cache()  # 임포트 완료 → 캐시 무효화
        return {"ok": True, "imported": len(reviews)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ← 여기가 핵심 수정: 데코레이터 누락 버그 수정
@app.post("/api/import-jasaol-chunk")
async def import_jasaol_chunk(request: Request):
    try:
        body = await request.json()
        reviews = body.get("reviews", [])
        replace = body.get("replace", False)
        CHUNK_PATH = DATA_PATH.parent / "jasaol_chunk.json"
        if replace:
            chunk_data = reviews
        else:
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
    try:
        CHUNK_PATH = DATA_PATH.parent / "jasaol_chunk.json"
        if not CHUNK_PATH.exists():
            raise HTTPException(status_code=400, detail="청크 데이터 없음")
        from scraper import JASAOL_BASE_PATH, JASAOL_NEW_PATH, safe_save as sc_save
        reviews = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
        sc_save(JASAOL_BASE_PATH, reviews)
        sc_save(JASAOL_NEW_PATH, [])
        CHUNK_PATH.unlink(missing_ok=True)
        data = {}
        if DATA_PATH.exists():
            try:
                data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        data.setdefault("changeok", {"jasa": [], "smartstore": []})
        data.setdefault("myeongga", {"jasa": [], "smartstore": []})
        data.setdefault("papa", {"jasa": [], "smartstore": []})
        data["last_updated"] = datetime.now().isoformat()
        sc_save(DATA_PATH, data)
        invalidate_cache()  # 임포트 완료 → 캐시 무효화
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


# ── 재고 관리 ──
INVENTORY_PATH = Path("data/inventory.json")

def load_inventory():
    if not INVENTORY_PATH.exists():
        return {"products": [], "history": [], "settings": {"hd_code": "HYW", "sp_code": "", "alert_threshold": 10, "warning_threshold": 20, "sync_interval": 30}}
    try:
        return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"products": [], "history": [], "settings": {}}

def save_inventory(data):
    INVENTORY_PATH.parent.mkdir(exist_ok=True)
    tmp = INVENTORY_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(INVENTORY_PATH)


@app.get("/competitor")
async def competitor_page():
    return FileResponse("static/competitor.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/100yearinventory")
async def inventory_input_page():
    return FileResponse("static/inventory_input.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})
@app.get("/inventory")
async def inventory_page():
    return FileResponse("static/inventory.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/api/inventory")
async def get_inventory():
    return JSONResponse(load_inventory())

@app.post("/api/inventory")
async def save_inventory_api(request: Request):
    try:
        data = await request.json()
        save_inventory(data)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 고객만족 설문 분석 ──
@app.get("/survey")
async def survey_page():
    return FileResponse("static/survey.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

@app.get("/api/survey")
async def get_survey_stats(date_from: str = None, date_to: str = None, product: str = None):
    """설문 통계 (마스킹된 데이터 기반). date_from/date_to(YYYY-MM-DD)로 기간 필터, product로 상품 필터."""
    import asyncio
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(None, survey_module.load_survey)
    stats = await loop.run_in_executor(None, survey_module.compute_survey_stats, payload, date_from, date_to, product)
    # 데이터가 없고 서비스 계정도 없으면 안내 메시지
    if stats.get("total_all", 0) == 0 and not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        stats["error"] = "구글 서비스 계정이 아직 연결되지 않았습니다. 환경변수 GOOGLE_SERVICE_ACCOUNT_JSON 등록 후 동기화하세요."
    elif stats.get("total_all", 0) == 0 and survey_state.get("last_error"):
        stats["error"] = f"수집 오류: {survey_state['last_error']}"
    return JSONResponse(stats)

@app.get("/api/survey/records")
async def get_survey_records():
    """마스킹된 설문 원본 레코드 (휴대폰번호는 이미 마스킹되어 저장됨)."""
    import asyncio
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(None, survey_module.load_survey)
    return JSONResponse({"records": payload.get("records", []), "count": payload.get("count", 0)})

@app.post("/api/survey/sync")
async def sync_survey(background_tasks: BackgroundTasks):
    """설문 수동 동기화 트리거."""
    if survey_state["running"]:
        return {"ok": False, "msg": "이미 동기화 중입니다"}
    background_tasks.add_task(run_survey_collect)
    return {"ok": True, "msg": "동기화 시작"}

@app.get("/api/survey/debug-columns")
async def survey_debug_columns():
    """진단: 시트 헤더 + 첫 3행 raw 값 (컬럼 매핑 확인용, 임시)."""
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        csv_text = await loop.run_in_executor(None, survey_module.fetch_sheet_csv)
        import csv as _csv, io as _io
        rows = list(_csv.reader(_io.StringIO(csv_text)))
        if not rows:
            return {"error": "빈 시트"}
        header = rows[0]
        data_rows = rows[1:]
        # 컬럼 수 분포
        from collections import Counter as _C
        len_dist = _C(len(r) for r in data_rows)
        # 헤더에서 휴대폰/나이/성별 컬럼 인덱스
        def find_col(kw):
            for i,h in enumerate(header):
                if kw in h: return i
            return -1
        phone_i = find_col("휴대폰")
        age_i = find_col("나이")
        gender_i = find_col("성별")
        # 해당 컬럼들의 실제 값 샘플 (다양한 행에서)
        def col_samples(i, n=8):
            if i < 0: return []
            out = []
            for r in data_rows:
                v = r[i] if i < len(r) else ""
                if v.strip():
                    out.append(v)
                if len(out) >= n: break
            return out
        return {
            "col_count": len(header),
            "row_count": len(data_rows),
            "len_distribution": dict(len_dist),
            "phone_idx": phone_i, "phone_samples": col_samples(phone_i),
            "age_idx": age_i, "age_samples": col_samples(age_i),
            "gender_idx": gender_i, "gender_samples": col_samples(gender_i),
            "header": header,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/survey/status")
async def survey_status():
    """설문 수집 상태 + 서비스 계정 이메일(공유 요청용)."""
    return {
        **survey_state,
        "service_account_email": survey_module.service_account_email(),
        "sheet_id": survey_module.SHEET_ID,
        "data_exists": survey_module.SURVEY_PATH.exists(),
    }


@app.post("/api/refresh-jasaol-recent")
async def refresh_jasaol_recent(days: int = 14):
    """최근 N일 자사몰 후기를 전문+사진으로 재수집하여 기존 데이터를 교체.
    같은 review_no는 전문 버전으로 덮어쓰고, 없으면 추가."""
    import asyncio
    from scraper import scrape_jasaol_recent, JASAOL_BASE_PATH, JASAOL_NEW_PATH, load_json, safe_save
    try:
        fresh = await scrape_jasaol_recent(days=days, progress_cb=progress_cb)
        if not fresh:
            return {"ok": True, "updated": 0, "added": 0, "msg": "수집된 후기 없음"}
        fresh_by_no = {str(r.get("review_no", "")): r for r in fresh if r.get("review_no")}

        updated = added = 0

        def merge_into(path):
            nonlocal updated, added
            data = load_json(path, [])
            existing_nos = {str(r.get("review_no", "")) for r in data if r.get("review_no")}
            out = []
            for r in data:
                rno = str(r.get("review_no", ""))
                if rno in fresh_by_no:
                    out.append(fresh_by_no[rno])  # 전문 버전으로 교체
                    updated += 1
                else:
                    out.append(r)
            safe_save(path, out)
            return existing_nos

        # base와 new 양쪽에서 교체
        nos_base = await asyncio.get_event_loop().run_in_executor(None, merge_into, JASAOL_BASE_PATH)
        nos_new = await asyncio.get_event_loop().run_in_executor(None, merge_into, JASAOL_NEW_PATH)
        all_existing = nos_base | nos_new

        # 기존에 없던 신규 후기는 new에 추가
        to_add = [r for no, r in fresh_by_no.items() if no not in all_existing]
        if to_add:
            new_data = load_json(JASAOL_NEW_PATH, [])
            new_data.extend(to_add)
            safe_save(JASAOL_NEW_PATH, new_data)
            added = len(to_add)

        invalidate_cache()
        return {"ok": True, "fetched": len(fresh), "updated": updated, "added": added,
                "with_images": sum(1 for r in fresh if r.get("images"))}
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "detail": traceback.format_exc()[:500]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# trigger redeploy
# redeploy
