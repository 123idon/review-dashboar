import json
import asyncio
import re
import httpx
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
CREMA_API   = "https://review6.cre.ma/api/papaes.com/reviews"
CREMA_WID   = 1
CREMA_PER   = 100
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
CREMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://review6.cre.ma/v2/papaes.com/products/reviews?product_code=2&widget_id=1",
    "Accept": "application/json, text/plain, */*",
}

# ── 자사몰(고도몰) ─────────────────────────────────────────────────────────────
JASAOL_BASE = "https://shop.100yearshop.co.kr"
JASAOL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
JASAOL_DELAY = 1.5   # 요청 간격(초) - 서버 부하 최소화


# ─────────────────────────── 명가 ────────────────────────────────────────────
def parse_myeongga_review(r):
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


async def scrape_myeongga(progress_cb=None):
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
            pct = int(done/len(offsets)*100)
            if progress_cb:
                progress_cb({"phase":"detail","done":done,"total":len(offsets),
                    "collected":len(all_reviews),"brand":"명가삼대떡집","progress_pct":pct,
                    "progress_msg":f"명가삼대떡집 {len(all_reviews):,}/{total:,}건 ({pct}%)"})
            await asyncio.sleep(0.05)
    print(f"  [명가삼대떡집] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 파파공방 Crema ────────────────────────────────────
def parse_crema_review(r: dict) -> dict:
    try:
        d = datetime.fromisoformat(r["created_at"][:19])
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
    score = float(r.get("score") or 0)
    content = re.sub(r'\s+', ' ', (r.get("filtered_message") or "").strip())[:500]
    author = (r.get("user_display_name") or "")[:20]
    product = (r.get("product_name") or "")[:80]
    ext = (r.get("external_platform_type") or "").lower()
    src = str(r.get("review_source") or "").lower()
    if "naver" in ext or "naver" in src:
        platform = "naver"
    elif "kakao" in ext or "kakao" in src:
        platform = "kakao"
    else:
        platform = "direct"
    return {"date": date_str, "score": score, "product": product,
            "title": "", "content": content, "platform": platform, "author": author}


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
        print(f"  papa idx={prod_code} p{page} → {len(all_reviews)}건")
        if progress_cb:
            progress_cb({"phase":"detail","done":prod_idx,"total":total_prods,
                "collected":len(all_reviews),"brand":"파파공방",
                "progress_msg":f"파파공방 idx={prod_code} {len(all_reviews)}건 수집 중..."})
        if not next_page:
            break
        page = next_page
        await asyncio.sleep(0.2)
    return all_reviews


async def scrape_papa(progress_cb=None):
    print("  [파파공방] Crema API 수집 시작")
    all_reviews = []
    async with httpx.AsyncClient(timeout=20, headers=CREMA_HEADERS, follow_redirects=True) as client:
        for i, prod_code in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_crema_product(client, prod_code, progress_cb, i, len(PAPA_PRODUCTS))
            all_reviews.extend(reviews)
            await asyncio.sleep(0.5)
    print(f"  [파파공방] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 자사몰(고도몰) ────────────────────────────────────
def fetch_html_euckr(resp: httpx.Response) -> BeautifulSoup:
    """EUC-KR 인코딩 처리"""
    html = resp.content.decode("euc-kr", errors="replace")
    return BeautifulSoup(html, "html.parser")


async def get_categories(client: httpx.AsyncClient) -> list[str]:
    """메인페이지에서 카테고리 URL 자동 수집"""
    try:
        resp = await client.get(f"{JASAOL_BASE}/shop/main/index.php", timeout=15)
        soup = fetch_html_euckr(resp)
        cats = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "goods_list.php" in href and "category=" in href:
                m = re.search(r"category=(\d+)", href)
                if m:
                    cat = m.group(1)
                    full = f"{JASAOL_BASE}/shop/goods/goods_list.php?category={cat}"
                    if full not in cats:
                        cats.append(full)
      cat_ids = [re.search(r'category=(\d+)', c).group(1) for c in cats]
        print(f"  [자사몰] 카테고리 {len(cats)}개 발견: {cat_ids}")
        return cats
    except Exception as e:
        print(f"  [자사몰] 카테고리 수집 실패: {e}")
        return []


async def get_goods_nos(client: httpx.AsyncClient, cat_url: str) -> list[int]:
    """카테고리 페이지에서 상품번호 수집 (전 페이지)"""
    goods_nos = []
    page = 1
    while True:
        try:
            url = f"{cat_url}&page={page}"
            resp = await client.get(url, timeout=15)
            soup = fetch_html_euckr(resp)
            found = []
            for a in soup.find_all("a", href=True):
                m = re.search(r"goodsno=(\d+)", a["href"])
                if m:
                    gno = int(m.group(1))
                    if gno not in goods_nos and gno not in found:
                        found.append(gno)
            if not found:
                break
            goods_nos.extend(found)
            await asyncio.sleep(JASAOL_DELAY)
            page += 1
            # 안전장치: 페이지 50개 초과 방지
            if page > 50:
                break
        except Exception as e:
            print(f"  [자사몰] 상품목록 수집 실패 {cat_url} p{page}: {e}")
            break
    return goods_nos


def parse_jasaol_review(row, product_name: str) -> dict | None:
    """후기 테이블 행 파싱"""
    try:
        tds = row.find_all("td")
        if len(tds) < 5:
            return None

        # 날짜 (보통 4번째~5번째 td)
        date_str = ""
        for td in tds:
            text = td.get_text(strip=True)
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                date_str = text[:10]
                break
        if not date_str:
            return None

        # 별점 (color:#14AA46 스타일)
        score = 0
        star_tds = [td for td in tds if "14AA46" in str(td)]
        if star_tds:
            stars_text = star_tds[0].get_text()
            score = stars_text.count("★")

        # 내용 (가장 긴 텍스트 td)
        content = ""
        for td in tds:
            t = td.get_text(separator=" ", strip=True)
            # 날짜/숫자/짧은 텍스트 제외
            if len(t) > len(content) and not re.match(r"^[\d\-\s★☆]+$", t):
                content = t

        content = re.sub(r"\s+", " ", content).strip()[:500]

        # 작성자
        author = ""
        for td in tds:
            t = td.get_text(strip=True)
            if re.match(r"^[가-힣a-zA-Z\*]{1,10}$", t) and len(t) >= 2:
                author = t
                break

        if not content or len(content) < 2:
            return None

        return {
            "date": date_str,
            "score": float(score) if score else 5.0,
            "product": product_name[:80],
            "title": "",
            "content": content,
            "platform": "direct",
            "author": author,
        }
    except Exception:
        return None


async def get_product_reviews(client: httpx.AsyncClient, goodsno: int, product_name: str) -> list[dict]:
    """상품 후기 전체 페이지 수집"""
    all_reviews = []
    page = 1
    while True:
        try:
            url = f"{JASAOL_BASE}/shop/goods/goods_review.php?goodsno={goodsno}&page={page}"
            resp = await client.get(url, timeout=15)
            soup = fetch_html_euckr(resp)

            # rv_tbl 클래스 테이블에서 후기 행 파싱
            tbl = soup.find("div", class_="rv_tbl")
            if not tbl:
                break

            rows = tbl.find_all("tr", onmouseover=True)
            if not rows:
                break

            found = 0
            for row in rows:
                rv = parse_jasaol_review(row, product_name)
                if rv:
                    all_reviews.append(rv)
                    found += 1

            if found == 0:
                break

            await asyncio.sleep(JASAOL_DELAY)
            page += 1
            if page > 200:  # 안전장치
                break

        except Exception as e:
            print(f"  [자사몰] 후기 수집 실패 goodsno={goodsno} p{page}: {e}")
            break

    return all_reviews


async def get_product_name(client: httpx.AsyncClient, goodsno: int) -> str:
    """상품명 조회"""
    try:
        resp = await client.get(
            f"{JASAOL_BASE}/shop/goods/goods_view.php?goodsno={goodsno}",
            timeout=15)
        soup = fetch_html_euckr(resp)
        # og:title 또는 title 태그에서 상품명 추출
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()[:80]
        if soup.title:
            return soup.title.get_text(strip=True)[:80]
    except Exception:
        pass
    return f"상품{goodsno}"


async def scrape_jasaol(progress_cb=None) -> list:
    print("  [자사몰] 수집 시작 (부하 최소화 모드)")
    all_reviews = []

    async with httpx.AsyncClient(
        headers=JASAOL_HEADERS,
        follow_redirects=True,
        timeout=15,
    ) as client:
        # 1) 카테고리 수집
        cat_urls = await get_categories(client)
        if not cat_urls:
            print("  [자사몰] 카테고리 없음 - 종료")
            return []
        await asyncio.sleep(JASAOL_DELAY)

        # 2) 상품번호 수집 (중복 제거)
        all_goods = []
        for cat_url in cat_urls:
            gnos = await get_goods_nos(client, cat_url)
            for g in gnos:
                if g not in all_goods:
                    all_goods.append(g)
            print(f"  카테고리 완료 → 누적 상품 {len(all_goods)}개")
            await asyncio.sleep(JASAOL_DELAY)

        print(f"  [자사몰] 총 상품 {len(all_goods)}개 → 후기 수집 시작")

        # 3) 상품별 후기 수집
        for idx, goodsno in enumerate(all_goods):
            product_name = await get_product_name(client, goodsno)
            await asyncio.sleep(JASAOL_DELAY)

            reviews = await get_product_reviews(client, goodsno, product_name)
            all_reviews.extend(reviews)

            pct = int((idx + 1) / len(all_goods) * 100)
            print(f"  [{idx+1}/{len(all_goods)}] {product_name} → {len(reviews)}건 (누적 {len(all_reviews)}건)")

            if progress_cb:
                progress_cb({
                    "phase": "detail",
                    "done": idx + 1,
                    "total": len(all_goods),
                    "collected": len(all_reviews),
                    "brand": "자사몰",
                    "progress_pct": pct,
                    "progress_msg": f"자사몰 {idx+1}/{len(all_goods)}개 상품 수집 중... ({pct}%)",
                })

    print(f"  [자사몰] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 메인 ────────────────────────────────────────────
async def collect_all(progress_cb=None):
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    myeongga_reviews = await scrape_myeongga(progress_cb)
    papa_reviews     = await scrape_papa(progress_cb)
    jasaol_reviews   = await scrape_jasaol(progress_cb)

    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok":  {"jasa": [],               "smartstore": []},
        "myeongga":  {"jasa": myeongga_reviews,  "smartstore": []},
        "papa":      {"jasa": papa_reviews,       "smartstore": []},
        "jasaol":    {"jasa": jasaol_reviews,     "smartstore": []},
    }
    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n완료! 명가={len(myeongga_reviews):,} 파파={len(papa_reviews):,} 자사몰={len(jasaol_reviews):,}건")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())
