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
JASAOL_DELAY   = 0      # 딜레이 제거
JASAOL_CONCURRENT = 20  # 동시 요청 20개


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

    # 임시파일에 배치마다 저장 (메모리 절약)
    tmp_path = DATA_PATH.parent / "myeongga_tmp.jsonl"
    tmp_path.parent.mkdir(exist_ok=True)
    tmp_f = open(tmp_path, "w", encoding="utf-8")
    count = 0
    done = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        for i in range(0, len(offsets), CONCURRENT):
            batch = offsets[i:i+CONCURRENT]
            results = await asyncio.gather(*[fetch_offset(client, off, sem) for off in batch])
            for _, items in results:
                for r in items:
                    parsed = parse_myeongga_review(r)
                    tmp_f.write(json.dumps(parsed, ensure_ascii=False) + "\n")
                    count += 1
            done += len(batch)
            pct = int(done / len(offsets) * 100)
            if progress_cb:
                progress_cb({"phase": "detail", "done": done, "total": len(offsets),
                    "collected": count, "brand": "명가삼대떡집", "progress_pct": int(pct*0.4),
                    "progress_msg": f"명가삼대떡집 {count:,}/{total:,}건 ({pct}%)"})
            await asyncio.sleep(0.05)

    tmp_f.close()

    # 임시파일 읽어서 리스트로 반환
    all_reviews = []
    with open(tmp_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_reviews.append(json.loads(line))
    tmp_path.unlink(missing_ok=True)  # 임시파일 삭제

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
            pct = 40 + int(((prod_idx + 1) / total_prods) * 15)
            progress_cb({"phase": "detail", "done": prod_idx, "total": total_prods,
                "collected": len(all_reviews), "brand": "파파공방", "progress_pct": pct,
                "progress_msg": f"파파공방 idx={prod_code} {len(all_reviews)}건 수집 중..."})
        if not next_page or page >= 500:  # 안전장치
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


async def get_product_reviews_incremental(client: httpx.AsyncClient, goodsno: int, product_name: str,
                                           sem: asyncio.Semaphore, since_date: str,
                                           progress_cb=None, idx=0, total=1) -> list:
    """since_date 이후 후기만 수집 - 최신순이므로 날짜 넘으면 즉시 중단"""
    all_reviews = []
    page = 1
    last_page_known = None

    while True:
        _, reviews, first_last_page = await fetch_review_page(client, goodsno, page, sem, product_name)

        # 첫 페이지에서 마지막 페이지 파악
        if page == 1 and first_last_page:
            last_page_known = first_last_page

        if not reviews:
            break

        stop = False
        new_found = 0
        for rv in reviews:
            if rv["date"] >= since_date:
                all_reviews.append(rv)
                new_found += 1
            else:
                stop = True  # 이 날짜 이전 → 더 볼 필요 없음
                break

        if stop:
            break

        # 다음 페이지 있는지 확인
        max_page = last_page_known or page
        if page >= max_page:
            break
        page += 1

    if all_reviews and progress_cb:
        progress_cb({
            "phase": "detail", "done": idx + 1, "total": total,
            "collected": len(all_reviews), "brand": "자사몰",
            "progress_pct": 58 + int(((idx + 1) / total) * 42),
            "progress_msg": f"자사몰 [{idx+1}/{total}] {product_name[:20]} +{len(all_reviews)}건",
        })

    return all_reviews


async def collect_goods_reviews(args):
    """병렬 처리용 wrapper"""
    client, goodsno, product_name, sem, since_date, progress_cb, idx, total = args
    return await get_product_reviews_incremental(
        client, goodsno, product_name, sem, since_date,
        progress_cb=progress_cb, idx=idx, total=total
    )


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

    # 기존 데이터에서 마지막 날짜 파악 → 증분 수집
    since_date = "2000-01-01"
    if DATA_PATH.exists():
        try:
            existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            existing_reviews = existing.get("jasaol", {}).get("jasa", [])
            if existing_reviews:
                dates = [r["date"] for r in existing_reviews if r.get("date")]
                if dates:
                    since_date = max(dates)
                    print(f"  [자사몰] 증분 수집: {since_date} 이후만 수집")
                    _cb(f"자사몰 증분 수집: {since_date} 이후 새 후기만", 56)
        except Exception:
            pass

    sem = asyncio.Semaphore(JASAOL_CONCURRENT)

    async with httpx.AsyncClient(
        headers=JASAOL_HEADERS, follow_redirects=True, timeout=15
    ) as client:
        goods_list = await get_categories_and_goods(client, progress_cb)
        if not goods_list:
            print("  [자사몰] 상품 없음 - 종료")
            return []

        total = len(goods_list)
        print(f"  [자사몰] 총 {total}개 상품 → 증분 수집 ({since_date} 이후, 5개 병렬)")
        _cb(f"자사몰 상품 {total}개, {since_date} 이후 수집 시작", 58, 0, total)

        # 상품 5개씩 병렬 처리
        GOODS_CONCURRENT = 5
        all_reviews = []
        done = 0

        for i in range(0, total, GOODS_CONCURRENT):
            batch = goods_list[i:i + GOODS_CONCURRENT]
            tasks = [
                collect_goods_reviews((client, gno, name, sem, since_date, progress_cb, i+j, total))
                for j, (gno, name) in enumerate(batch)
            ]
            results = await asyncio.gather(*tasks)
            for reviews in results:
                all_reviews.extend(reviews)
            done += len(batch)
            pct = 58 + int(done / total * 42)
            _cb(f"자사몰 {done}/{total}개 완료 (누적 {len(all_reviews):,}건)", pct, done, total, len(all_reviews))

    # 기존 데이터에 새 후기 병합 (중복 제거)
    if DATA_PATH.exists() and since_date != "2000-01-01":
        try:
            existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            existing_reviews = existing.get("jasaol", {}).get("jasa", [])
            # 기존 + 새 것 합치되 since_date 이전 기존 것 유지
            merged = existing_reviews + all_reviews
            print(f"  [자사몰] 병합: 기존 {len(existing_reviews):,} + 신규 {len(all_reviews):,} = {len(merged):,}건")
            all_reviews = merged
        except Exception as e:
            print(f"  [자사몰] 병합 실패: {e}")

    print(f"  [자사몰] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 메인 ────────────────────────────────────────────
async def collect_all(progress_cb=None) -> dict:
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 기존 데이터 로드 (중간실패시 보존용)
    existing = {}
    if DATA_PATH.exists():
        try:
            existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 브랜드별로 수집 → 즉시 저장 → 메모리 해제
    # 최종 결과는 파일에서 읽어서 반환
    base = {
        "last_updated": datetime.now().isoformat(),
        "changeok": existing.get("changeok", {"jasa": [], "smartstore": []}),
        "myeongga": existing.get("myeongga", {"jasa": [], "smartstore": []}),
        "papa":     existing.get("papa",     {"jasa": [], "smartstore": []}),
        "jasaol":   existing.get("jasaol",   {"jasa": [], "smartstore": []}),
    }
    del existing
    safe_save(base)  # 초기 저장

    try:
        reviews = await scrape_myeongga(progress_cb)
        # 파일 업데이트: myeongga만 교체
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["myeongga"]["jasa"] = reviews
        data["last_updated"] = datetime.now().isoformat()
        safe_save(data)
        del reviews, data
        print("  [중간저장] 명가 완료")
    except Exception as e:
        print(f"  [명가] 수집 실패: {e}")

    try:
        reviews = await scrape_papa(progress_cb)
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["papa"]["jasa"] = reviews
        data["last_updated"] = datetime.now().isoformat()
        safe_save(data)
        del reviews, data
        print("  [중간저장] 파파공방 완료")
    except Exception as e:
        print(f"  [파파공방] 수집 실패: {e}")

    try:
        reviews = await scrape_jasaol(progress_cb)
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["jasaol"]["jasa"] = reviews
        data["last_updated"] = datetime.now().isoformat()
        safe_save(data)
        del reviews, data
        print("  [중간저장] 자사몰 완료")
    except Exception as e:
        print(f"  [자사몰] 수집 실패: {e}")

    # 최종 데이터 파일에서 읽어서 반환
    final = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    m = len(final.get("myeongga", {}).get("jasa", []))
    p = len(final.get("papa", {}).get("jasa", []))
    j = len(final.get("jasaol", {}).get("jasa", []))
    print(f"\n완료! 명가={m:,} 파파={p:,} 자사몰={j:,}건")
    return final


if __name__ == "__main__":
    asyncio.run(collect_all())