import json
import asyncio
import re
import httpx
import tempfile
import os
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

DATA_PATH = Path("data/reviews.json")

# ── 명가삼대떡집 vreview ──────────────────────────────────────────────────────
VREVIEW_ID = "53f3f70e-66b2-45f9-9a05-369e4dc2f2c5"
API_BASE   = f"https://one.vreview.tv/api/embed/v2/{VREVIEW_ID}/reviews/"
LIMIT      = 100
CONCURRENT = 20

# ── 파파공방 Crema ─────────────────────────────────────────────────────────────
CREMA_API     = "https://review6.cre.ma/api/papaes.com/reviews"
CREMA_WID     = 1
CREMA_PER     = 100
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
CREMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://review6.cre.ma/v2/papaes.com/products/reviews?product_code=2&widget_id=1",
    "Accept": "application/json, text/plain, */*",
}

# ── 자사몰(고도몰) ─────────────────────────────────────────────────────────────
JASAOL_BASE    = "https://shop.100yearshop.co.kr"
JASAOL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://shop.100yearshop.co.kr/",
}
JASAOL_DELAY   = 0.2   # 딜레이 0.5→0.2초
JASAOL_CONCURRENT = 5  # 동시 요청 수 (서버 부하 낮은 수준)


# ── 안전한 JSON 저장 ──────────────────────────────────────────────────────────
def safe_save(data: dict):
    DATA_PATH.parent.mkdir(exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)


# ─────────────────────────── 명가삼대떡집 ────────────────────────────────────
def parse_myeongga_review(r: dict) -> dict:
    try:
        d = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
    origin = (r.get("origin_from") or "").lower()
    platform = "naver" if "naver" in origin else "kakao" if "kakao" in origin else "direct"
    return {
        "date": date_str, "score": r.get("rating", 0) or 0,
        "product": ((r.get("product") or {}).get("name") or "")[:80],
        "title": (r.get("title") or "")[:100],
        "content": (r.get("text") or "")[:500],
        "platform": platform, "author": "",
    }


async def fetch_offset(client: httpx.AsyncClient, offset: int, sem: asyncio.Semaphore):
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


async def scrape_myeongga(progress_cb=None) -> list:
    print("  [명가삼대떡집] vreview API 수집 시작")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{API_BASE}?limit=1&offset=0")
        total = resp.json().get("count", 0)
    print(f"  총 {total:,}건 → {(total//LIMIT)+1}번 요청")
    offsets = list(range(0, total, LIMIT))
    sem = asyncio.Semaphore(CONCURRENT)
    all_reviews = []
    done = 0
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i in range(0, len(offsets), CONCURRENT):
            batch = offsets[i:i+CONCURRENT]
            results = await asyncio.gather(*[fetch_offset(client, off, sem) for off in batch])
            for _, items in results:
                all_reviews.extend([parse_myeongga_review(r) for r in items])
            done += len(batch)
            pct = int(done / len(offsets) * 100)
            if progress_cb:
                progress_cb({"phase": "detail", "done": done, "total": len(offsets),
                    "collected": len(all_reviews), "brand": "명가삼대떡집", "progress_pct": int(pct*0.4),
                    "progress_msg": f"명가삼대떡집 {len(all_reviews):,}/{total:,}건 ({pct}%)"})
            await asyncio.sleep(0.05)
    print(f"  [명가삼대떡집] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 파파공방 Crema ───────────────────────────────────
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
    return {"date": date_str, "score": score,
            "product": (r.get("product_name") or "")[:80],
            "title": "", "content": content, "platform": platform,
            "author": (r.get("user_display_name") or "")[:20]}


async def fetch_crema_product(client, prod_code, progress_cb=None, prod_idx=0, total_prods=6):
    all_reviews = []
    page = 1
    while True:
        try:
            r = await client.get(CREMA_API,
                params={"product_code": prod_code, "page": page, "per": CREMA_PER, "widget_id": CREMA_WID},
                timeout=20)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            print(f"  papa idx={prod_code} p{page} 실패: {e}")
            break
        reviews = d.get("reviews", [])
        if not reviews:
            break
        for rv in reviews:
            all_reviews.append(parse_crema_review(rv))
        next_page = d.get("pagy", {}).get("next")
        if progress_cb:
            pct = 40 + int(((prod_idx + 1) / total_prods) * 15)  # 40~55%
            progress_cb({"phase": "detail", "done": prod_idx, "total": total_prods,
                "collected": len(all_reviews), "brand": "파파공방", "progress_pct": pct,
                "progress_msg": f"파파공방 idx={prod_code} {len(all_reviews)}건 수집 중..."})
        if not next_page:
            break
        page = next_page
        await asyncio.sleep(0.2)
    return all_reviews


async def scrape_papa(progress_cb=None) -> list:
    print("  [파파공방] Crema API 수집 시작")
    all_reviews = []
    async with httpx.AsyncClient(timeout=20, headers=CREMA_HEADERS, follow_redirects=True) as client:
        for i, prod_code in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_crema_product(client, prod_code, progress_cb, i, len(PAPA_PRODUCTS))
            all_reviews.extend(reviews)
            await asyncio.sleep(0.3)
    print(f"  [파파공방] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 자사몰(고도몰) ──────────────────────────────────
def fetch_html_euckr(resp: httpx.Response) -> BeautifulSoup:
    html = resp.content.decode("euc-kr", errors="replace")
    return BeautifulSoup(html, "html.parser")


def get_last_page(soup: BeautifulSoup) -> int:
    """페이지네이션에서 마지막 페이지 번호 추출"""
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
        # 날짜: td[4] 우선
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
        # 별점
        score = 0
        if len(tds) > 5 and "14AA46" in str(tds[5]):
            score = tds[5].get_text().count("★")
        else:
            for td in tds:
                if "14AA46" in str(td):
                    score = td.get_text().count("★")
                    break
        # 내용: td[2]
        content = ""
        if len(tds) > 2:
            content = tds[2].get_text(separator=" ", strip=True)
        if len(content) < 5:
            for td in tds[2:]:
                t = td.get_text(separator=" ", strip=True)
                if len(t) > len(content) and not re.match(r"^[\d\-\s★☆]+$", t):
                    content = t
        content = re.sub(r"\s+", " ", content).strip()[:500]
        # 작성자
        author = ""
        if len(tds) > 3:
            t = tds[3].get_text(strip=True)
            if re.match(r"^[가-힣a-zA-Z\*]{1,10}$", t) and len(t) >= 2:
                author = t
        if not content or len(content) < 2:
            return None
        return {"date": date_str, "score": float(score),
                "product": product_name[:80], "title": "",
                "content": content, "platform": "direct", "author": author}
    except Exception:
        return None


async def fetch_review_page(client: httpx.AsyncClient, goodsno: int, page: int, sem: asyncio.Semaphore, product_name: str):
    """단일 후기 페이지 수집 - sem 해제 후 딜레이"""
    url = f"{JASAOL_BASE}/shop/goods/goods_review.php?goodsno={goodsno}&page={page}"
    result = (page, [], 0)
    async with sem:
        try:
            resp = await client.get(url, timeout=15)
            soup = fetch_html_euckr(resp)
            tbl = soup.find("div", class_="rv_tbl")
            if tbl:
                rows = tbl.find_all("tr", onmouseover=True)
                reviews = [rv for row in rows for rv in [parse_jasaol_review(row, product_name)] if rv]
                last_page = get_last_page(soup) if page == 1 else 0
                result = (page, reviews, last_page)
        except Exception as e:
            print(f"  [자사몰] goodsno={goodsno} p{page} 실패: {e}")
    # sem 해제 후 딜레이 - 다른 요청 대기 안 막음
    await asyncio.sleep(JASAOL_DELAY)
    return result


async def get_product_reviews_fast(client: httpx.AsyncClient, goodsno: int, product_name: str,
                                    sem: asyncio.Semaphore) -> list:
    """첫 페이지로 전체 페이지수 파악 후 병렬 수집"""
    # 1) 첫 페이지 수집 + 마지막 페이지 번호 파악
    _, first_reviews, last_page = await fetch_review_page(client, goodsno, 1, sem, product_name)
    if not first_reviews:
        return []
    if last_page <= 1:
        return first_reviews

    # 2) 나머지 페이지 병렬 수집 (JASAOL_CONCURRENT개씩)
    all_reviews = list(first_reviews)
    pages = list(range(2, last_page + 1))

    for i in range(0, len(pages), JASAOL_CONCURRENT * 3):
        batch = pages[i:i + JASAOL_CONCURRENT * 3]
        tasks = [fetch_review_page(client, goodsno, p, sem, product_name) for p in batch]
        results = await asyncio.gather(*tasks)
        for _, reviews, _ in results:
            all_reviews.extend(reviews)

    return all_reviews


async def get_categories_and_goods(client: httpx.AsyncClient, progress_cb=None) -> list:
    def _cb(msg, pct=56):
        if progress_cb:
            progress_cb({"phase": "detail", "done": 0, "total": 1, "collected": 0,
                "brand": "자사몰", "progress_pct": pct, "progress_msg": msg})

    try:
        _cb("자사몰 메인페이지 접속 중...", 56)
        resp = await client.get(f"{JASAOL_BASE}/shop/main/index.php", timeout=15)
        print(f"  [자사몰] 메인페이지 status={resp.status_code}")
        soup = fetch_html_euckr(resp)
        cat_ids = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"category=(\d+)", a["href"])
            if m and "goods_list.php" in a["href"]:
                cid = m.group(1)
                if cid not in cat_ids:
                    cat_ids.append(cid)
        print(f"  [자사몰] 카테고리 {len(cat_ids)}개 발견: {cat_ids}")
        _cb(f"자사몰 카테고리 {len(cat_ids)}개 발견", 57)
    except Exception as e:
        print(f"  [자사몰] 카테고리 수집 실패: {e}")
        _cb(f"자사몰 카테고리 수집 실패: {e}", 56)
        return []

    if not cat_ids:
        print("  [자사몰] 카테고리 0개")
        _cb("자사몰 카테고리 0개 - 수집 불가", 56)
        return []

    await asyncio.sleep(JASAOL_DELAY)

    goods = {}
    for idx, cid in enumerate(cat_ids):
        page = 1
        while True:
            try:
                url = f"{JASAOL_BASE}/shop/goods/goods_list.php?category={cid}&page={page}"
                resp = await client.get(url, timeout=15)
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
                await asyncio.sleep(JASAOL_DELAY)
                page += 1
                if page > 50:
                    break
            except Exception as e:
                print(f"  [자사몰] 상품목록 수집 실패 cat={cid} p{page}: {e}")
                break
        pct = 57 + int((idx + 1) / len(cat_ids) * 1)
        _cb(f"카테고리 {cid} 완료 → 상품 {len(goods)}개", pct)
        await asyncio.sleep(JASAOL_DELAY)

    return list(goods.items())


async def scrape_jasaol(progress_cb=None) -> list:
    def _cb(msg, pct=58, done=0, total=1, collected=0):
        if progress_cb:
            progress_cb({"phase": "detail", "done": done, "total": total,
                "collected": collected, "brand": "자사몰",
                "progress_pct": pct, "progress_msg": msg})

    print("  [자사몰] 수집 시작")
    _cb("자사몰 카테고리 수집 중...", 55)
    all_reviews = []

    sem = asyncio.Semaphore(JASAOL_CONCURRENT)

    async with httpx.AsyncClient(
        headers=JASAOL_HEADERS, follow_redirects=True, timeout=15
    ) as client:
        goods_list = await get_categories_and_goods(client, progress_cb)
        if not goods_list:
            print("  [자사몰] 상품 없음 - 종료")
            return []

        total = len(goods_list)
        print(f"  [자사몰] 총 {total}개 상품 → 병렬 후기 수집 시작 (동시 {JASAOL_CONCURRENT}개)")
        _cb(f"자사몰 상품 {total}개 발견, 후기 수집 시작...", 58, 0, total)

        for idx, (goodsno, product_name) in enumerate(goods_list):
            reviews = await get_product_reviews_fast(client, goodsno, product_name, sem)
            all_reviews.extend(reviews)
            pct = 58 + int((idx + 1) / total * 42)
            msg = f"자사몰 [{idx+1}/{total}] {product_name[:20]} → {len(reviews)}건 (누적 {len(all_reviews):,}건)"
            print(f"  {msg}")
            _cb(msg, pct, idx + 1, total, len(all_reviews))

    print(f"  [자사몰] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 메인 ────────────────────────────────────────────
async def collect_all(progress_cb=None) -> dict:
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    existing = {}
    if DATA_PATH.exists():
        try:
            existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": existing.get("changeok", {"jasa": [], "smartstore": []}),
        "myeongga": existing.get("myeongga", {"jasa": [], "smartstore": []}),
        "papa":     existing.get("papa",     {"jasa": [], "smartstore": []}),
        "jasaol":   existing.get("jasaol",   {"jasa": [], "smartstore": []}),
    }

    try:
        myeongga_reviews = await scrape_myeongga(progress_cb)
        result["myeongga"]["jasa"] = myeongga_reviews
        safe_save(result)
        print("  [중간저장] 명가 완료")
    except Exception as e:
        print(f"  [명가] 수집 실패: {e}")

    try:
        papa_reviews = await scrape_papa(progress_cb)
        result["papa"]["jasa"] = papa_reviews
        safe_save(result)
        print("  [중간저장] 파파공방 완료")
    except Exception as e:
        print(f"  [파파공방] 수집 실패: {e}")

    try:
        jasaol_reviews = await scrape_jasaol(progress_cb)
        result["jasaol"]["jasa"] = jasaol_reviews
        safe_save(result)
        print("  [중간저장] 자사몰 완료")
    except Exception as e:
        print(f"  [자사몰] 수집 실패: {e}")

    result["last_updated"] = datetime.now().isoformat()
    safe_save(result)

    m = len(result["myeongga"]["jasa"])
    p = len(result["papa"]["jasa"])
    j = len(result["jasaol"]["jasa"])
    print(f"\n완료! 명가={m:,} 파파={p:,} 자사몰={j:,}건")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())