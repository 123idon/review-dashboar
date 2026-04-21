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

# ── 파파공방 Crema ─────────────────────────────────────────────────────────────
CREMA_API   = "https://review6.cre.ma/api/papaes.com/reviews"
CREMA_WID   = 1        # list_v3 pc widget id
CREMA_PER   = 100      # 페이지당 최대
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
CREMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://review6.cre.ma/v2/papaes.com/products/reviews?product_code=2&widget_id=1",
    "Accept": "application/json, text/plain, */*",
}
PAPA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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

    # 플랫폼 판별
    ext = (r.get("external_platform_type") or "").lower()
    src = str(r.get("review_source") or "").lower()
    if "naver" in ext or "naver" in src:
        platform = "naver"
    elif "kakao" in ext or "kakao" in src:
        platform = "kakao"
    else:
        platform = "direct"

    return {
        "date": date_str,
        "score": score,
        "product": product,
        "title": "",
        "content": content,
        "platform": platform,
        "author": author,
    }


async def fetch_crema_product(client: httpx.AsyncClient, prod_code: int, progress_cb=None, prod_idx=0, total_prods=6) -> list:
    """Crema JSON API로 상품 전체 리뷰 수집"""
    all_reviews = []
    page = 1

    while True:
        try:
            r = await client.get(
                CREMA_API,
                params={"product_code": prod_code, "page": page, "per": CREMA_PER, "widget_id": CREMA_WID},
                timeout=20,
            )
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            print(f"  idx={prod_code} p{page} 실패: {e}")
            break

        reviews = d.get("reviews", [])
        if not reviews:
            break

        for rv in reviews:
            all_reviews.append(parse_crema_review(rv))

        pagy = d.get("pagy", {})
        total_items = pagy.get("items", 0)
        next_page = pagy.get("next")

        pct = int((prod_idx + page * CREMA_PER / max(total_items * (page / max(page,1)), 1)) / total_prods * 100)
        print(f"  idx={prod_code} p{page} → 누적 {len(all_reviews)}건")

        if progress_cb:
            progress_cb({
                "phase": "detail", "done": prod_idx, "total": total_prods,
                "collected": len(all_reviews), "brand": "파파공방",
                "progress_pct": min(pct, 99),
                "progress_msg": f"파파공방 idx={prod_code} {len(all_reviews)}건 수집 중...",
            })

        if not next_page:
            break

        page = next_page
        await asyncio.sleep(0.2)

    print(f"  idx={prod_code} 완료: {len(all_reviews)}건")
    return all_reviews


async def scrape_papa(progress_cb=None) -> list:
    print("  [파파공방] Crema API 수집 시작")
    all_reviews = []

    async with httpx.AsyncClient(
        timeout=20,
        headers=CREMA_HEADERS,
        follow_redirects=True,
    ) as client:
        for i, prod_code in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_crema_product(client, prod_code, progress_cb, i, len(PAPA_PRODUCTS))
            all_reviews.extend(reviews)
            await asyncio.sleep(0.5)

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
