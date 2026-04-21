import json
import asyncio
import re
import httpx
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("data/reviews.json")

# ── 명가삼대떡집 vreview ──────────────────────────────────────────────────────
VREVIEW_ID = "53f3f70e-66b2-45f9-9a05-369e4dc2f2c5"
API_BASE   = f"https://one.vreview.tv/api/embed/v2/{VREVIEW_ID}/reviews/"
LIMIT      = 100
CONCURRENT = 20

# ── 파파공방 Crema JSONP ──────────────────────────────────────────────────────
PAPA_BASE     = "https://www.papaes.com"
CREMA_BASE    = "https://review6.cre.ma"
CREMA_MID     = "papaes.com"
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
PAPA_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.papaes.com/",
}


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
            print(f"  {done}/{len(offsets)} 완료 → {len(all_reviews):,}건 ({pct}%)")
            if progress_cb:
                progress_cb({"phase":"detail","done":done,"total":len(offsets),
                    "collected":len(all_reviews),"brand":"명가삼대떡집","progress_pct":pct,
                    "progress_msg":f"명가삼대떡집 {len(all_reviews):,}/{total:,}건 ({pct}%)"})
            await asyncio.sleep(0.05)
    print(f"  [명가삼대떡집] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 파파공방 Crema ───────────────────────────────────
def parse_jsonp(text: str) -> dict:
    """JSONP 응답 cb({...}) → dict"""
    s = text.strip()
    s = re.sub(r'^[^(]+\(', '', s).rstrip(');')
    return json.loads(s)


def parse_crema_review(r: dict, product_name: str) -> dict:
    """Crema 리뷰 객체 → 내부 포맷"""
    # 날짜
    raw = r.get("created_at") or r.get("date") or ""
    try:
        d = datetime.fromisoformat(raw[:19].replace("T", " ").replace(" ", "T"))
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")

    score = float(r.get("rating") or r.get("score") or 0)
    content = re.sub(r'\s+', ' ', (r.get("body") or r.get("content") or "").strip())[:500]
    author = (r.get("member") or {}).get("name") or r.get("name") or ""

    # 상품명: Crema는 product 객체 또는 product_name 필드
    prod = (r.get("product") or {})
    pname = prod.get("name") or r.get("product_name") or product_name

    return {
        "date": date_str,
        "score": score,
        "product": str(pname)[:80],
        "title": (r.get("title") or "")[:100],
        "content": content,
        "platform": "direct",
        "author": str(author)[:20],
    }


def parse_jsonld_review(r: dict, product_name: str) -> dict:
    """JSON-LD 리뷰 (fallback)"""
    try:
        d = datetime.fromisoformat(r.get("datePublished","")[:19])
        date_str = d.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")
    score = float((r.get("reviewRating") or {}).get("ratingValue", 0) or 0)
    content = re.sub(r'\s+', ' ', (r.get("reviewBody") or "").strip())[:500]
    author = ((r.get("author") or {}).get("name") or "")[:20]
    return {"date":date_str,"score":score,"product":product_name[:80],
            "title":"","content":content,"platform":"direct","author":author}


async def fetch_crema_product(client: httpx.AsyncClient, prod_code: int) -> list:
    """Crema JSONP API로 상품 전체 리뷰 수집, fallback → JSON-LD"""

    # 1) 총 리뷰 수 확인
    try:
        r = await client.get(
            f"{CREMA_BASE}/{CREMA_MID}/api/v1/products/reviews_count"
            f"?product_codes[]={prod_code}&callback=cb&app=0",
            timeout=15
        )
        total = parse_jsonp(r.text).get(str(prod_code), 0)
        print(f"  idx={prod_code} Crema 총 리뷰: {total}건")
    except Exception as e:
        print(f"  idx={prod_code} 총 리뷰 수 확인 실패: {e} → JSON-LD fallback")
        return await fetch_jsonld_product(client, prod_code)

    if total == 0:
        return []

    # 2) 페이지별 수집
    PER = 100
    pages = (total // PER) + (1 if total % PER else 0)
    all_reviews = []

    # 상품명 먼저 파악
    try:
        r_name = await client.get(
            f"{CREMA_BASE}/{CREMA_MID}/api/v1/products/reviews_score"
            f"?product_codes[]={prod_code}&callback=cb&app=0",
            timeout=10
        )
        # reviews_score는 score만 있고 name은 없음 - JSON-LD에서 가져옴
        product_name = await get_product_name(client, prod_code)
    except Exception:
        product_name = f"상품{prod_code}"

    for page in range(1, pages + 1):
        try:
            r = await client.get(
                f"{CREMA_BASE}/{CREMA_MID}/api/v1/reviews"
                f"?product_code={prod_code}&page={page}&per={PER}&callback=cb&app=0",
                timeout=20
            )
            data = parse_jsonp(r.text)
            reviews_raw = data.get("reviews") or data.get("data") or []
            if not reviews_raw:
                # 다른 키 구조 시도
                if isinstance(data, list):
                    reviews_raw = data
                else:
                    print(f"  idx={prod_code} p{page} 빈 응답: {list(data.keys())}")
                    break
            for rv in reviews_raw:
                all_reviews.append(parse_crema_review(rv, product_name))
            print(f"  idx={prod_code} p{page}/{pages} → 누적 {len(all_reviews)}건")
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"  idx={prod_code} p{page} 실패: {e}")
            await asyncio.sleep(1)

    if not all_reviews:
        print(f"  idx={prod_code} Crema 0건 → JSON-LD fallback")
        return await fetch_jsonld_product(client, prod_code)

    return all_reviews


async def get_product_name(client: httpx.AsyncClient, idx: int) -> str:
    """JSON-LD에서 상품명만 추출"""
    try:
        r = await client.get(f"{PAPA_BASE}/shop_view/?idx={idx}", timeout=15)
        ld = re.findall(r'application/ld\+json[^>]*>(.*?)</script>', r.text, re.DOTALL)
        for b in ld:
            try:
                d = json.loads(b.strip())
                if d.get("@type") == "Product":
                    return d.get("name", f"상품{idx}")
            except Exception:
                continue
    except Exception:
        pass
    return f"상품{idx}"


async def fetch_jsonld_product(client: httpx.AsyncClient, idx: int) -> list:
    """JSON-LD fallback - 최근 5건"""
    for attempt in range(4):
        try:
            if attempt > 0:
                await asyncio.sleep(2.0 * attempt)
            r = await client.get(f"{PAPA_BASE}/shop_view/?idx={idx}", timeout=20)
            r.raise_for_status()
            ld = re.findall(r'application/ld\+json[^>]*>(.*?)</script>', r.text, re.DOTALL)
            pname = f"상품{idx}"
            reviews = []
            for b in ld:
                try:
                    d = json.loads(b.strip())
                    if d.get("@type") != "Product":
                        continue
                    pname = d.get("name", pname)
                    for rv in d.get("review", []):
                        reviews.append(parse_jsonld_review(rv, pname))
                except Exception:
                    continue
            print(f"  idx={idx} JSON-LD fallback → {len(reviews)}건")
            return reviews
        except Exception as e:
            print(f"  idx={idx} fallback 시도{attempt+1} 실패: {e}")
    return []


async def scrape_papa(progress_cb=None) -> list:
    print("  [파파공방] Crema API 수집 시작")
    all_reviews = []
    total_products = len(PAPA_PRODUCTS)

    async with httpx.AsyncClient(timeout=20, headers=PAPA_HEADERS,
                                  follow_redirects=True) as client:
        for i, prod_code in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_crema_product(client, prod_code)
            all_reviews.extend(reviews)
            pct = int((i + 1) / total_products * 100)
            if progress_cb:
                progress_cb({
                    "phase": "detail", "done": i+1, "total": total_products,
                    "collected": len(all_reviews), "brand": "파파공방",
                    "progress_pct": pct,
                    "progress_msg": f"파파공방 {i+1}/{total_products}개 상품 ({pct}%)",
                })
            await asyncio.sleep(1.5)

    print(f"  [파파공방] 최종 {len(all_reviews):,}건")
    return all_reviews


# ─────────────────────────── 메인 ────────────────────────────────────────────
async def collect_all(progress_cb=None):
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    myeongga_reviews = await scrape_myeongga(progress_cb)
    papa_reviews     = await scrape_papa(progress_cb)
    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": {"jasa": [], "smartstore": []},
        "myeongga": {"jasa": myeongga_reviews, "smartstore": []},
        "papa":     {"jasa": papa_reviews,     "smartstore": []},
    }
    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n완료! 명가={len(myeongga_reviews):,}건, 파파공방={len(papa_reviews):,}건")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())
