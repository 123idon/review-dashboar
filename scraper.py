import json
import asyncio
import re
import httpx
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("data/reviews.json")

VREVIEW_ID = "53f3f70e-66b2-45f9-9a05-369e4dc2f2c5"
API_BASE   = f"https://one.vreview.tv/api/embed/v2/{VREVIEW_ID}/reviews/"
LIMIT      = 100
CONCURRENT = 20

PAPA_BASE     = "https://www.papaes.com"
PAPA_PRODUCTS = [2, 10, 78, 79, 80, 84]
PAPA_HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


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


def parse_papa_review(r, product_name):
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


async def fetch_papa_product(client, idx, retries=4):
    url = f"{PAPA_BASE}/shop_view/?idx={idx}"
    for attempt in range(retries):
        try:
            if attempt > 0:
                await asyncio.sleep(2.0 * attempt)
            resp = await client.get(url, timeout=20.0)
            resp.raise_for_status()
            html = resp.text
            ld_blocks = re.findall(r'application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL)
            product_name = f"상품{idx}"
            reviews = []
            for block in ld_blocks:
                try:
                    data = json.loads(block.strip())
                    if data.get("@type") != "Product":
                        continue
                    product_name = data.get("name", product_name)
                    for rv in data.get("review", []):
                        reviews.append(parse_papa_review(rv, product_name))
                except Exception:
                    continue
            print(f"  idx={idx} [{product_name}] → {len(reviews)}건")
            return reviews
        except Exception as e:
            print(f"  idx={idx} 시도{attempt+1} 실패: {e}")
    return []


async def scrape_papa(progress_cb=None):
    print("  [파파공방] imweb 수집 시작")
    all_reviews = []
    total = len(PAPA_PRODUCTS)
    async with httpx.AsyncClient(timeout=20.0, headers=PAPA_HEADERS) as client:
        for i, idx in enumerate(PAPA_PRODUCTS):
            reviews = await fetch_papa_product(client, idx)
            all_reviews.extend(reviews)
            pct = int((i+1)/total*100)
            if progress_cb:
                progress_cb({"phase":"detail","done":i+1,"total":total,
                    "collected":len(all_reviews),"brand":"파파공방","progress_pct":pct,
                    "progress_msg":f"파파공방 {i+1}/{total}개 상품 수집 중... ({pct}%)"})
            await asyncio.sleep(1.5)
    print(f"  [파파공방] 최종 {len(all_reviews):,}건")
    return all_reviews


async def collect_all(progress_cb=None):
    print("="*50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    myeongga_reviews = await scrape_myeongga(progress_cb)
    papa_reviews     = await scrape_papa(progress_cb)
    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": {"jasa":[],"smartstore":[]},
        "myeongga": {"jasa":myeongga_reviews,"smartstore":[]},
        "papa":     {"jasa":papa_reviews,    "smartstore":[]},
    }
    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH,"w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n완료! 명가={len(myeongga_reviews):,}건, 파파공방={len(papa_reviews):,}건")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())
