import json
import asyncio
import re
import httpx
import os
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

DATA_PATH = Path("data/reviews.json")
JASAOL_BASE_PATH = Path("data/jasaol_base.json")
JASAOL_NEW_PATH = Path("data/jasaol_new.json")

VREVIEW_ID = "53f3f70e-66b2-45f9-9a05-369e4dc2f2c5"
API_BASE = f"https://one.vreview.tv/api/embed/v2/{VREVIEW_ID}/reviews/"
LIMIT = 100
CONCURRENT = 20

CREMA_API = "https://review6.cre.ma/api/papaes.com/reviews"
CREMA_WID = 1
CREMA_PER = 100
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
CREMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://review6.cre.ma/v2/papaes.com/products/reviews?product_code=2&widget_id=1",
    "Accept": "application/json, text/plain, */*",
}

JASAOL_BASE = "https://shop.100yearshop.co.kr"
JASAOL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://shop.100yearshop.co.kr/",
}
JASAOL_DELAY = 0.1
JASAOL_CONCURRENT = 5
GOODS_CONCURRENT = 3
JASAOL_PAGE_TIMEOUT = 8
JASAOL_TOTAL_TIMEOUT = 600

def safe_save(path: Path, data):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def load_jasaol_reviews() -> list:
    base = load_json(JASAOL_BASE_PATH, [])
    new = load_json(JASAOL_NEW_PATH, [])
    return base + new

def get_jasaol_since_date() -> str:
    dates = []
    for path in [JASAOL_BASE_PATH, JASAOL_NEW_PATH]:
        data = load_json(path, [])
        if isinstance(data, list):
            dates.extend(r["date"] for r in data if r.get("date"))
    return max(dates) if dates else "2000-01-01"

def get_brand_since_date(brand_key: str) -> str:
    """reviews.json에서 특정 브랜드의 마지막 수집 날짜 반환"""
    data = load_json(DATA_PATH, {})
    reviews = data.get(brand_key, {}).get("jasa", [])
    dates = [r["date"] for r in reviews if r.get("date")]
    return max(dates) if dates else "2000-01-01"

# ─────────────────────────── 명가삼대떡집 ──────────────────────────────────────
def parse_myeongga_review(r: dict) -> dict:
    try:
        d = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
    origin = (r.get("origin_from") or "").lower()
    platform = "naver" if "naver" in origin else "kakao" if "kakao" in origin else "direct"
    return {
        "date": date_str,
        "score": r.get("rating", 0) or 0,
        "product": ((r.get("product") or {}).get("name") or "")[:80],
        "title": (r.get("title") or "")[:100],
        "content": (r.get("text") or "")[:500],
        "platform": platform,
        "author": "",
    }

async def fetch_offset(client, offset, sem):
    url = (f"{API_BASE}?expand=created_at,product,rating"
           f"&limit={LIMIT}&offset={offset}&ordering=-created_at")
    async with sem:
        try:
            resp = await client.get(url, timeout=20.0)
            resp.raise_for_status()
            return offset, resp.json().get("results", [])
        except Exception as e:
            print(f"  offset={offset} 실패: {e}")
            return offset, []

async def scrape_myeongga(progress_cb=None, since_date: str = "2000-01-01") -> list:
    """since_date 이후 신규만 수집해서 기존 데이터에 병합 반환"""
    print(f"  [명가삼대떡집] vreview API 수집 시작 (since={since_date})")
    existing = load_json(DATA_PATH, {}).get("myeongga", {}).get("jasa", [])

    new_reviews = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{API_BASE}?limit=1&offset=0")
        total = resp.json().get("count", 0)
        offsets = list(range(0, total, LIMIT))
        sem = asyncio.Semaphore(CONCURRENT)
        done = 0
        stop_fetching = False

        async with httpx.AsyncClient(timeout=20.0) as client2:
            for i in range(0, len(offsets), CONCURRENT):
                if stop_fetching:
                    break
                batch = offsets[i:i+CONCURRENT]
                results = await asyncio.gather(*[fetch_offset(client2, off, sem) for off in batch])
                for _, items in results:
                    for r in items:
                        parsed = parse_myeongga_review(r)
                        if parsed["date"] < since_date:
                            stop_fetching = True
                            break
                        new_reviews.append(parsed)
                    if stop_fetching:
                        break
                done += len(batch)
                pct = int(done / len(offsets) * 40)
                if progress_cb:
                    progress_cb({"phase": "detail", "done": done, "total": len(offsets),
                                 "collected": len(new_reviews), "brand": "명가삼대떡집",
                                 "progress_pct": pct,
                                 "progress_msg": f"명가삼대떡집 신규 {len(new_reviews):,}건 수집 중..."})
                await asyncio.sleep(0.05)

    # 기존 데이터에서 since_date 이전 것 + 신규 병합
    old = [r for r in existing if r.get("date", "") < since_date]
    merged = new_reviews + old
    print(f"  [명가삼대떡집] 신규 {len(new_reviews):,}건 + 기존 {len(old):,}건 = {len(merged):,}건")
    return merged

# ─────────────────────────── 파파공방 Crema ─────────────────────────────────────
def parse_crema_review(r: dict) -> dict:
    try:
        d = datetime.fromisoformat(r["created_at"][:19])
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
    score = float(r.get("score") or 0)
    content = re.sub(r'\s+', ' ', (r.get("filtered_message") or "").strip())[:500]
    ext = (r.get("external_platform_type") or "").lower()
    src = str(r.get("review_source") or "").lower()
    platform = "naver" if ("naver" in ext or "naver" in src) else "kakao" if ("kakao" in ext or "kakao" in src) else "direct"
    return {"date": date_str, "score": score, "product": (r.get("product_name") or "")[:80],
            "title": "", "content": content, "platform": platform,
            "author": (r.get("user_display_name") or "")[:20]}

async def fetch_crema_product(client, prod_code, since_date="2000-01-01",
                               progress_cb=None, prod_idx=0, total_prods=6):
    all_reviews = []
    page = 1
    while True:
        try:
            r = await client.get(CREMA_API, params={"product_code": prod_code, "page": page,
                                                     "per": CREMA_PER, "widget_id": CREMA_WID}, timeout=20)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            print(f"  papa idx={prod_code} p{page} 실패: {e}")
            break
        reviews = d.get("reviews", [])
        if not reviews:
            break
        stop = False
        for rv in reviews:
            parsed = parse_crema_review(rv)
            if parsed["date"] < since_date:
                stop = True
                break
            all_reviews.append(parsed)
        next_page = d.get("pagy", {}).get("next")
        if progress_cb:
            pct = 40 + int(((prod_idx + 1) / total_prods) * 15)
            progress_cb({"phase": "detail", "done": prod_idx, "total": total_prods,
                         "collected": len(all_reviews), "brand": "파파공방", "progress_pct": pct,
                         "progress_msg": f"파파공방 idx={prod_code} 신규 {len(all_reviews)}건 수집 중..."})
        if stop or not next_page or page >= 500:
            break
        page = next_page
        await asyncio.sleep(0.2)
    return all_reviews

async def scrape_papa(progress_cb=None, since_date: str = "2000-01-01") -> list:
    """since_date 이후 신규만 수집해서 기존 데이터에 병합 반환"""
    print(f"  [파파공방] Crema API 수집 시작 (since={since_date})")
    existing = load_json(DATA_PATH, {}).get("papa", {}).get("jasa", [])

    new_reviews = []
    async with httpx.AsyncClient(timeout=20, headers=CREMA_HEADERS, follow_redirects=True) as client:
        for i, prod_code in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_crema_product(client, prod_code, since_date,
                                                 progress_cb, i, len(PAPA_PRODUCTS))
            new_reviews.extend(reviews)
            await asyncio.sleep(0.3)

    old = [r for r in existing if r.get("date", "") < since_date]
    merged = new_reviews + old
    print(f"  [파파공방] 신규 {len(new_reviews):,}건 + 기존 {len(old):,}건 = {len(merged):,}건")
    return merged

# ─────────────────────────── 자사몰(고도몰) ─────────────────────────────────────
def fetch_html_euckr(resp: httpx.Response) -> BeautifulSoup:
    html = resp.content.decode("euc-kr", errors="replace")
    return BeautifulSoup(html, "html.parser")

def get_last_page(soup: BeautifulSoup) -> int:
    max_page = 1
    for a in soup.find_all("a", href=True):
        if "goods_review" in a["href"]:
            m = re.search(r"page=(\d+)", a["href"])
            if m:
                p = int(m.group(1))
                if p > max_page:
                    max_page = p
    return max_page

def parse_jasaol_review(row, product_name: str):
    try:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 5:
            return None
        date_str = ""
        if len(tds) > 4:
            t = tds[4].get_text(strip=True)
            if re.match(r"\d{4}-\d{2}-\d{2}", t):
                date_str = t[:10]
        if not date_str:
            for td in tds:
                t = td.get_text(strip=True)
                if re.match(r"\d{4}-\d{2}-\d{2}", t):
                    date_str = t[:10]
                    break
        if not date_str:
            return None
        score = 0
        if len(tds) > 5 and "14AA46" in str(tds[5]):
            score = tds[5].get_text().count("★")
        else:
            for td in tds:
                if "14AA46" in str(td):
                    score = td.get_text().count("★")
                    break
        content = ""
        if len(tds) > 2:
            content = tds[2].get_text(separator=" ", strip=True)
        if len(content) < 5:
            for td in tds[2:]:
                t = td.get_text(separator=" ", strip=True)
                if len(t) > len(content) and not re.match(r"^[\d\-\s★☆]+$", t):
                    content = t
        content = re.sub(r"\s+", " ", content).strip()[:500]
        author = ""
        if len(tds) > 3:
            t = tds[3].get_text(strip=True)
            if re.match(r"^[가-힣a-zA-Z\*]{1,10}$", t) and len(t) >= 2:
                author = t
        if not content or len(content) < 2:
            return None
        return {"date": date_str, "score": float(score), "product": product_name[:80],
                "title": "", "content": content, "platform": "direct", "author": author}
    except Exception:
        return None

async def fetch_review_page(client, goodsno, page, sem, product_name):
    url = f"{JASAOL_BASE}/shop/goods/goods_review.php?goodsno={goodsno}&page={page}"
    result = (page, [], 0)
    async with sem:
        try:
            resp = await client.get(url, timeout=JASAOL_PAGE_TIMEOUT)
            soup = fetch_html_euckr(resp)
            tbl = soup.find("div", class_="rv_tbl")
            if tbl:
                rows = tbl.find_all("tr", onmouseover=True)
                reviews = [rv for row in rows for rv in [parse_jasaol_review(row, product_name)] if rv]
                last_page = get_last_page(soup) if page == 1 else 0
                result = (page, reviews, last_page)
        except asyncio.TimeoutError:
            print(f"  [자사몰] goodsno={goodsno} p{page} 타임아웃 ({JASAOL_PAGE_TIMEOUT}초)")
        except Exception as e:
            print(f"  [자사몰] goodsno={goodsno} p{page} 실패: {e}")
    await asyncio.sleep(JASAOL_DELAY)
    return result

async def get_new_reviews_for_good(client, goodsno, product_name, sem, since_date):
    all_reviews = []
    page = 1
    last_page_known = None
    while True:
        _, reviews, first_last = await fetch_review_page(client, goodsno, page, sem, product_name)
        if page == 1 and first_last:
            last_page_known = first_last
        if not reviews:
            break
        stop = False
        for rv in reviews:
            if rv["date"] >= since_date:
                all_reviews.append(rv)
            else:
                stop = True
                break
        if stop:
            break
        max_page = last_page_known or page
        if page >= max_page:
            break
        page += 1
    return all_reviews

async def get_categories_and_goods(client, progress_cb=None) -> list:
    def _cb(msg, pct=56):
        if progress_cb:
            progress_cb({"phase": "detail", "done": 0, "total": 1, "collected": 0,
                         "brand": "자사몰", "progress_pct": pct, "progress_msg": msg})
    try:
        _cb("자사몰 메인페이지 접속 중...", 56)
        resp = await client.get(f"{JASAOL_BASE}/shop/main/index.php", timeout=JASAOL_PAGE_TIMEOUT)
        soup = fetch_html_euckr(resp)
        cat_ids = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"category=(\d+)", a["href"])
            if m and "goods_list.php" in a["href"]:
                cid = m.group(1)
                if cid not in cat_ids:
                    cat_ids.append(cid)
        print(f"  [자사몰] 카테고리 {len(cat_ids)}개: {cat_ids}")
        _cb(f"카테고리 {len(cat_ids)}개 발견", 57)
    except asyncio.TimeoutError:
        print(f"  [자사몰] 메인페이지 타임아웃 ({JASAOL_PAGE_TIMEOUT}초)")
        return []
    except Exception as e:
        print(f"  [자사몰] 카테고리 수집 실패: {e}")
        return []

    if not cat_ids:
        return []

    await asyncio.sleep(0.2)
    goods = {}
    for cid in cat_ids:
        page = 1
        while True:
            try:
                resp = await client.get(
                    f"{JASAOL_BASE}/shop/goods/goods_list.php?category={cid}&page={page}",
                    timeout=JASAOL_PAGE_TIMEOUT)
                soup = fetch_html_euckr(resp)
                found = 0
                for a in soup.find_all("a", href=True):
                    m = re.search(r"goodsno=(\d+)", a["href"])
                    if not m:
                        continue
                    gno = int(m.group(1))
                    if gno in goods:
                        continue
                    name = a.get_text(strip=True)
                    if not name:
                        img = a.find("img")
                        name = img.get("alt", "") if img else ""
                    if len(name) >= 2:
                        goods[gno] = name[:80]
                        found += 1
                if found == 0:
                    break
                await asyncio.sleep(0.1)
                page += 1
                if page > 50:
                    break
            except asyncio.TimeoutError:
                print(f"  [자사몰] cat={cid} p{page} 타임아웃")
                break
            except Exception as e:
                print(f"  [자사몰] cat={cid} p{page} 실패: {e}")
                break
    return list(goods.items())

async def scrape_jasaol_incremental(progress_cb=None) -> list:
    since_date = get_jasaol_since_date()
    print(f"  [자사몰] 증분 수집: {since_date} 이후")

    def _cb(msg, pct=58, done=0, total=1, collected=0):
        if progress_cb:
            progress_cb({"phase": "detail", "done": done, "total": total, "collected": collected,
                         "brand": "자사몰", "progress_pct": pct, "progress_msg": msg})

    _cb(f"자사몰 {since_date} 이후 신규 후기 수집 시작", 55)
    sem = asyncio.Semaphore(JASAOL_CONCURRENT)
    all_new = []

    try:
        async with asyncio.timeout(JASAOL_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(headers=JASAOL_HEADERS, follow_redirects=True,
                                         timeout=JASAOL_PAGE_TIMEOUT) as client:
                goods_list = await get_categories_and_goods(client, progress_cb)
                if not goods_list:
                    print("  [자사몰] 상품 목록 없음, 건너뜀")
                    return []

                total = len(goods_list)
                _cb(f"상품 {total}개, {since_date} 이후 수집 시작", 58, 0, total)

                done = 0
                for i in range(0, total, GOODS_CONCURRENT):
                    batch = goods_list[i:i+GOODS_CONCURRENT]
                    tasks = [
                        get_new_reviews_for_good(client, gno, name, sem, since_date)
                        for gno, name in batch
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, list):
                            all_new.extend(r)
                        elif isinstance(r, Exception):
                            print(f"  [자사몰] 상품 수집 오류: {r}")
                    done += len(batch)
                    pct = 58 + int(done / total * 42)
                    _cb(f"자사몰 {done}/{total}개 완료 (신규 {len(all_new):,}건)", pct, done, total, len(all_new))

    except asyncio.TimeoutError:
        print(f"  [자사몰] 전체 타임아웃 ({JASAOL_TOTAL_TIMEOUT}초) — 수집된 것만 저장")

    print(f"  [자사몰] 신규 {len(all_new):,}건")
    return all_new

# ─────────────────────────── 메인 ──────────────────────────────────────────────
async def collect_all(progress_cb=None) -> dict:
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 명가: since_date 이후 증분 + 기존 병합
    try:
        since = get_brand_since_date("myeongga")
        reviews = await scrape_myeongga(progress_cb, since_date=since)
        data = load_json(DATA_PATH, {})
        data.setdefault("changeok", {"jasa": [], "smartstore": []})
        data.setdefault("myeongga", {"jasa": [], "smartstore": []})
        data.setdefault("papa", {"jasa": [], "smartstore": []})
        data["myeongga"]["jasa"] = reviews
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        del reviews, data
        print("  [저장] 명가 완료")
    except Exception as e:
        print(f"  [명가] 실패: {e}")

    # 파파: since_date 이후 증분 + 기존 병합
    try:
        since = get_brand_since_date("papa")
        reviews = await scrape_papa(progress_cb, since_date=since)
        data = load_json(DATA_PATH, {})
        data["papa"]["jasa"] = reviews
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        del reviews, data
        print("  [저장] 파파공방 완료")
    except Exception as e:
        print(f"  [파파공방] 실패: {e}")

    # 자사몰: 증분 → jasaol_new.json에 누적 (중복 제거)
    try:
        since_before = get_jasaol_since_date()
        new_reviews = await scrape_jasaol_incremental(progress_cb)
        existing_new = load_json(JASAOL_NEW_PATH, [])
        combined = [r for r in existing_new if r.get("date", "") >= since_before] + new_reviews
        # 중복 제거: (date, author, content) 기준 - 같은 사람이 같은날 같은 내용을 여러상품에 쓴 경우 1건만
        seen = set()
        deduped = []
        for rv in combined:
            key = (rv.get("date",""), rv.get("author",""), rv.get("content","")[:80], rv.get("product","")[:40])
            if key not in seen:
                seen.add(key)
                deduped.append(rv)
        merged_new = deduped
        safe_save(JASAOL_NEW_PATH, merged_new)
        del new_reviews, existing_new, merged_new
        data = load_json(DATA_PATH, {})
        data["last_updated"] = datetime.now().isoformat()
        safe_save(DATA_PATH, data)
        del data
        print("  [저장] 자사몰 완료")
    except Exception as e:
        print(f"  [자사몰] 실패: {e}")

    print(f"수집 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return load_json(DATA_PATH, {})

if __name__ == "__main__":
    asyncio.run(collect_all())
