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
from analyzer import compute_stats, get_reviews_page, validate_range
import survey_module
import naver_automation as naver_auto
import daily_report
import asyncio
from smartstore_import import merge_reviews, validate_reviews

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
        # Imported/public Naver rows may say "naver", which otherwise means
        # Naver Pay on the direct shop. Classify by their source file on read.
        smartstore = [dict(r, platform="smartstore") for r in load_json(SMARTSTORE_PATH, [])]
        from review_identity import review_identity
        # Distinct review IDs must survive even when masked names/text match.
        seen_keys = set()
        jasaol_all = []
        for rv in jasaol_base + jasaol_new + smartstore:
            key = review_identity(rv)
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
from naver_seller import router as naver_seller_router
app.include_router(naver_seller_router)
Path("static").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
DAILY_REPORT_LOCK = asyncio.Lock()
DAILY_REPORT_DIR = DATA_PATH.parent / "daily_reports"

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

JASAOL_REPAIR_RUNNING = False

async def run_collect(only_jasaol=False):
    if collect_state["running"] or JASAOL_REPAIR_RUNNING:
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
        await collect_all(progress_cb=progress_cb, only_jasaol=only_jasaol)
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
    scheduler.add_job(run_collect, "cron", hour=0, minute=6, id="daily",
                      coalesce=True, max_instances=1, misfire_grace_time=3600)
    # Midnight includes competitors; remaining hours collect our own store only.
    scheduler.add_job(run_collect, "cron", hour="1-23", minute=6, id="jasaol_hourly",
                      kwargs={"only_jasaol": True}, coalesce=True, max_instances=1,
                      misfire_grace_time=3600)
    scheduler.add_job(run_survey_collect, "cron", hour=0, minute=20, id="survey_daily")
    scheduler.add_job(run_naver_collect, "cron", hour=0, minute=0, id="naver_daily",
                      coalesce=True, max_instances=1, misfire_grace_time=3600)
    scheduler.add_job(run_daily_report, "cron", hour=9, minute=0, id="daily_report",
                      coalesce=True, max_instances=1, misfire_grace_time=3600)
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
    # Account sessions are no longer used. Remove any retired session material.
    naver_auto.AUTH.unlink(missing_ok=True)
    (naver_auto.DATA / "naver_private" / "paired.json").unlink(missing_ok=True)
    # A cooldown persists across deployments; only one catch-up per eligible day.
    state = naver_auto.status()
    if state.get("last_success", "")[:10] != naver_auto.now()[:10]:
        asyncio.create_task(run_naver_collect())
    asyncio.create_task(ensure_daily_report())
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

async def run_daily_report():
    from scraper import safe_save
    async with DAILY_REPORT_LOCK:
        def generate():
            target = daily_report.yesterday()
            cache = _load_reviews_cached()
            if not cache:
                raise RuntimeError("후기 자료를 읽지 못했습니다.")
            report = daily_report.build_report(cache, target, naver_auto.status())
            DAILY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
            safe_save(DAILY_REPORT_DIR / f"{target}.json", report)
            return report
        return await asyncio.to_thread(generate)


async def ensure_daily_report():
    path = DAILY_REPORT_DIR / f"{daily_report.yesterday()}.json"
    try:
        if path.exists():
            report = json.loads(path.read_text(encoding="utf-8"))
            generated = datetime.fromisoformat(report["generated_at"])
            clock = datetime.now(daily_report.KST)
            morning = clock.replace(hour=9, minute=0, second=0, microsecond=0)
            if report.get("schema_version", 1) >= 3 and (clock < morning or generated >= morning):
                return report
        return await run_daily_report()
    except Exception as exc:
        print(f"전일 종합 생성 실패: {type(exc).__name__}")
        return None


@app.get("/api/daily-report/dates")
async def get_daily_report_dates():
    return JSONResponse({"dates": daily_report.report_dates(DAILY_REPORT_DIR),
                         "latest_target": daily_report.yesterday()}, headers={"Cache-Control": "no-store"})


@app.post("/api/daily-report/refresh")
async def refresh_daily_report():
    # Explicit refresh is restricted to the current previous-day report.
    # Historical date snapshots are never regenerated through this endpoint.
    invalidate_cache()
    try:
        report = await run_daily_report()
        return JSONResponse({"ok": True, "date": report["date"],
                             "generated_at": report["generated_at"], "total": report["total"]})
    except Exception:
        raise HTTPException(503, "보고서 갱신에 실패했습니다. 기존 보고서는 보존됩니다.")


@app.get("/api/daily-report")
async def get_daily_report(date: str = None):
    if date is not None:
        try:
            daily_report.valid_report_date(date)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if date > daily_report.yesterday():
            raise HTTPException(400, "전일 이전의 보고서 날짜를 선택해 주세요.")
    target = date or daily_report.yesterday()
    if target == daily_report.yesterday():
        report = await ensure_daily_report()
        if report is None:
            raise HTTPException(503, "전일 종합 보고서를 생성하지 못했습니다.")
    else:
        try:
            report = daily_report.read_report(DAILY_REPORT_DIR, target)
        except FileNotFoundError:
            raise HTTPException(404, "선택한 날짜에 저장된 보고서가 없습니다.")
        except (ValueError, OSError):
            raise HTTPException(503, "저장된 보고서를 읽지 못했습니다.")
    if report.get("schema_version", 1) < 2 or (
        daily_report.report_period(target)['period_days'] == 3
        and report.get('date_from') != daily_report.report_period(target)['date_from']
    ):
        # Legacy snapshots contain only excerpts. Preserve the stored original and
        # explicitly label the full-date view reconstructed from current stored rows.
        original_generated = report.get("generated_at")
        cache = await asyncio.to_thread(_load_reviews_cached)
        if not cache:
            raise HTTPException(503, "전체 후기 자료를 읽지 못했습니다.")
        report = daily_report.build_report(cache, target, naver_auto.status())
        report["reconstructed"] = True
        report["original_generated_at"] = original_generated
    job = scheduler.get_job("daily_report")
    report.update(daily_report.report_period(target))
    result = daily_report.select_report(report)
    result.pop('analysis', None)
    result['statistics'] = daily_report.statistics(report)
    result["next_run"] = job.next_run_time.isoformat() if job and scheduler.running else None
    result["available_dates"] = daily_report.report_dates(DAILY_REPORT_DIR)
    result["historical"] = target != daily_report.yesterday()
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


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
    try:
        validate_range(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
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
    keyword: str = None,
):
    """후기 목록 페이지네이션 전용 API"""
    try:
        validate_range(date_from, date_to)
        if shop not in ('jasaol', 'smartstore', 'myeongga', 'papa', 'changeok'):
            raise ValueError("지원하지 않는 브랜드입니다.")
        if not 1 <= size <= 10000 or page < 1 or filter_type not in ('all', 'low', 'jasa', 'ss'):
            raise ValueError("후기 목록 조회 조건이 올바르지 않습니다.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
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
        keyword=keyword,
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
    """쿠키 만료 여부 + 수집 중단 감지(마지막 후기가 N일 이상 오래됐으면 경고)"""
    from scraper import load_json
    result = dict(SMARTSTORE_STATUS)
    result["automation"] = naver_auto.status()
    job = scheduler.get_job("naver_daily")
    result["automation"]["next_run"] = job.next_run_time.isoformat() if job and scheduler.running else None
    result["import_mode"] = "merge"
    result["last_import"] = load_json(DATA_PATH.parent / "smartstore_import_status.json", None)
    try:
        reviews = load_json(DATA_PATH.parent / "smartstore.json", [])
        last = max((r.get('date','') for r in reviews), default='') or None
        result.update(naver_auto.collection_health(result['automation'], last))
    except Exception:
        result.update(stalled=True, collection_verified=False, data_freshness='unknown',
                      error='저장된 네이버 후기 상태를 확인하지 못했습니다.')
    if result.get('manual_action_required'):
        result['automation']['next_scheduled_check'] = result['automation'].get('next_run')
        result['automation']['next_run'] = None
        result['automation']['auto_resume'] = False
    return result

@app.post("/api/smartstore-cookie-ok")
async def smartstore_cookie_ok():
    SMARTSTORE_STATUS["cookie_expired"] = False
    SMARTSTORE_STATUS["expired_at"] = None
    return {"ok": True}

def smartstore_chunk_path(import_id: str = ""):
    import re
    if not isinstance(import_id, str) or (import_id and not re.fullmatch(r"[a-f0-9]{32}", import_id)):
        raise HTTPException(status_code=400, detail="잘못된 업로드 ID")
    suffix = "_" + import_id if import_id else ""
    return DATA_PATH.parent / f"smartstore_chunk{suffix}.json"


@app.post("/api/import-smartstore-chunk")
async def import_smartstore_chunk(request: Request):
    try:
        body = await request.json()
        reviews = body.get("reviews", [])
        validate_reviews(reviews)
        replace = body.get("replace", False)
        CHUNK_PATH = smartstore_chunk_path(body.get("import_id", ""))
        if replace:
            chunk_data = reviews
        else:
            existing = []
            if CHUNK_PATH.exists():
                try:
                    existing = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
                except Exception:
                    raise HTTPException(status_code=409, detail="업로드 파일 손상. 처음부터 다시 업로드해주세요.")
            chunk_data = existing + reviews
        from scraper import safe_save
        safe_save(CHUNK_PATH, chunk_data)
        return {"ok": True, "total": len(chunk_data)}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/import-smartstore-done")
async def import_smartstore_done(import_id: str = "", expected_count: int = 0):
    try:
        CHUNK_PATH = smartstore_chunk_path(import_id)
        if not CHUNK_PATH.exists():
            raise HTTPException(status_code=400, detail="청크 없음")
        from scraper import safe_save, load_json
        SMARTSTORE_PATH = DATA_PATH.parent / "smartstore.json"
        reviews = json.loads(CHUNK_PATH.read_text(encoding="utf-8"))
        if expected_count and len(reviews) != expected_count:
            raise HTTPException(status_code=409, detail="전송 건수 불일치. 기존 후기는 변경하지 않았습니다.")
        # Read strictly: a corrupt source must never be mistaken for an empty store.
        existing = json.loads(SMARTSTORE_PATH.read_text(encoding="utf-8")) if SMARTSTORE_PATH.exists() else []
        merged, summary = merge_reviews(existing, reviews)
        if SMARTSTORE_PATH.exists() and (summary["added"] or summary["updated"]):
            backup = DATA_PATH.parent / "smartstore_backups"
            backup.mkdir(exist_ok=True)
            safe_save(backup / f"before_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json", existing)
        safe_save(SMARTSTORE_PATH, merged)
        summary["completed_at"] = datetime.now().astimezone().isoformat()
        summary["latest_review_date"] = max(r["date"] for r in merged if r.get("date"))
        safe_save(DATA_PATH.parent / "smartstore_import_status.json", summary)
        CHUNK_PATH.unlink(missing_ok=True)
        data = load_json(DATA_PATH, {})
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        invalidate_cache()  # 임포트 완료 → 캐시 무효화
        return {"ok": True, **summary}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_naver_collect():
    import asyncio
    import time
    from datetime import timedelta
    from uuid import uuid4
    from scraper import safe_save, load_json
    from naver_public import collect, CollectionStopped
    import naver_seller
    if naver_seller.SESSION:
        return {"ok": False, "state": "connecting"}
    if naver_auto.LOCK.locked():
        return {"ok": False, "state": "running"}
    state = naver_auto.status()
    if float(state.get("retry_at") or 0) > time.time():
        return {"ok": False, "state": "cooldown"}
    if state.get("state") in ("not_allowed", "layout_changed", "unverified", "partial"):
        # These require adapter review; do not make blind daily retries.
        return {"ok": False, "state": state["state"]}
    async with naver_auto.LOCK:
        naver_auto.record("running", "로그인 없이 공개 상품 후기를 확인하고 있습니다.", started_at=naver_auto.now())
        try:
            existing = load_json(DATA_PATH.parent / "smartstore.json", [])
            latest = max((r.get("date", "") for r in existing), default="")
            since = (datetime.fromisoformat(latest) - timedelta(days=7)).date().isoformat() if latest else "2000-01-01"
            rows, details = await asyncio.wait_for(naver_seller.collect(since) if state.get('mode') == 'seller' else collect(since), timeout=1800)
            if rows:
                sid = uuid4().hex
                safe_save(smartstore_chunk_path(sid), rows)
                result = await import_smartstore_done(sid, len(rows))
            else:
                result = {"added": 0}
            naver_auto.record("ready", ("판매자 화면" if state.get('mode') == 'seller' else "공개 후기") + " 자동 수집 정상 · 매일 한국시간 00:00",
                              last_success=naver_auto.now(), received=len(rows), added=result["added"],
                              retry_at=0, **details)
            write_log(True, f"네이버 공개 후기: {len(rows)}건 확인, {result['added']}건 추가")
            return {"ok": True, "added": result["added"], "received": len(rows)}
        except CollectionStopped as exc:
            naver_auto.record(exc.state, str(exc), retry_at=exc.retry_at or 0)
            write_log(False, str(exc))
            return {"ok": False, "state": exc.state}
        except Exception as exc:
            message = "판매자 화면 수집 실패 · 인증 만료 또는 화면 변경 확인 필요. 기존 후기는 유지합니다." if state.get('mode') == 'seller' else "공개 후기 수집 실패. 기존 후기를 유지하며 계정 로그인은 시도하지 않습니다."
            naver_auto.record("error", message, error_type=type(exc).__name__, retry_at=time.time()+86400)
            write_log(False, message)
            return {"ok": False, "state": "error"}


@app.post("/api/naver-automation/connect")
async def connect_naver_automation(request: Request):
    # Do not even read the request body: login/session uploads have been retired.
    raise HTTPException(410, "계정 연결 기능이 폐지되었습니다. 공개 후기 수집은 네이버 아이디를 사용하지 않습니다.")


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
async def refresh_jasaol_recent(days: int = 14, start_page: int = 1):
    """최근 N일 자사몰 후기를 전문+사진으로 재수집하여 기존 데이터를 교체.
    같은 review_no는 전문 버전으로 덮어쓰고, 없으면 추가."""
    import asyncio
    from scraper import scrape_jasaol_recent, JASAOL_BASE_PATH, JASAOL_NEW_PATH, load_json, safe_save
    global JASAOL_REPAIR_RUNNING
    if not 1 <= days <= 365 or start_page < 1:
        raise HTTPException(400, "복구 기간은 1~365일이어야 합니다.")
    if collect_state["running"] or JASAOL_REPAIR_RUNNING:
        raise HTTPException(409, "후기 수집이 진행 중입니다. 완료 후 다시 시도해 주세요.")
    JASAOL_REPAIR_RUNNING = True
    try:
        audit = {}
        fresh = await scrape_jasaol_recent(days=days, progress_cb=progress_cb, audit=audit, start_page=start_page)
        if not fresh:
            return {"ok": True, "updated": 0, "added": 0, "msg": "수집된 후기 없음", "audit": audit}
        fresh_by_no = {str(r.get("review_no", "")): r for r in fresh if r.get("review_no")}

        updated = added = 0

        def merge_into(path):
            nonlocal updated, added
            data = load_json(path, [])
            backup = DATA_PATH.parent / "jasaol_backups"
            backup.mkdir(exist_ok=True)
            safe_save(backup / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json", data)
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
                "with_images": sum(1 for r in fresh if r.get("images")), "audit": audit,
                "oldest_fetched": min(r["date"] for r in fresh), "newest_fetched": max(r["date"] for r in fresh)}
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "detail": traceback.format_exc()[:500]})
    finally:
        JASAOL_REPAIR_RUNNING = False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# trigger redeploy
# redeploy
