import json
import asyncio
import httpx
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("data/reviews.json")

VREVIEW_ID = "53f3f70e-66b2-45f9-9a05-369e4dc2f2c5"
API_BASE   = f"https://one.vreview.tv/api/embed/v2/{VREVIEW_ID}/reviews/"
LIMIT      = 100   # 요청당 건수
CONCURRENT = 20    # 동시 요청 수


def parse_review(r: dict) -> dict:
    # 날짜
    try:
        d = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        date_str = d.strftime("%Y-%m-%d")
    except:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 플랫폼
    origin = (r.get("origin_from") or "").lower()
    if "naver" in origin:
        platform = "naver"
    elif "kakao" in origin:
        platform = "kakao"
    else:
        platform = "direct"

    return {
        "date":     date_str,
        "score":    r.get("rating", 0) or 0,
        "product":  ((r.get("product") or {}).get("name") or "")[:80],
        "title":    (r.get("title") or "")[:100],
        "content":  (r.get("text") or "")[:500],
        "platform": platform,
        "author":   "",
    }


async def fetch_offset(client: httpx.AsyncClient, offset: int, sem: asyncio.Semaphore):
    url = (
        f"{API_BASE}"
        f"?expand=created_at,product,rating"
        f"&limit={LIMIT}"
        f"&offset={offset}"
        f"&ordering=-created_at"
    )
    async with sem:
        try:
            resp = await client.get(url, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            return offset, data.get("results", [])
        except Exception as e:
            print(f"  offset={offset} 실패: {e}")
            return offset, []


async def scrape_myeongga(progress_cb=None) -> list:
    print("  [명가삼대떡집] vreview API 수집 시작")

    # 1) 총 건수 파악
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{API_BASE}?limit=1&offset=0")
        total = resp.json().get("count", 0)

    print(f"  총 {total:,}건 → {(total // LIMIT) + 1}번 요청 예정")

    offsets = list(range(0, total, LIMIT))
    sem = asyncio.Semaphore(CONCURRENT)
    all_reviews = []
    done = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        # CONCURRENT 단위 배치
        for i in range(0, len(offsets), CONCURRENT):
            batch = offsets[i:i + CONCURRENT]
            tasks = [fetch_offset(client, off, sem) for off in batch]
            results = await asyncio.gather(*tasks)

            for offset, items in results:
                for r in items:
                    all_reviews.append(parse_review(r))

            done += len(batch)
            pct = int(done / len(offsets) * 100)
            print(f"  {done}/{len(offsets)} 배치 완료 → 누적 {len(all_reviews):,}건 ({pct}%)")

            if progress_cb:
                progress_cb({
                    "phase":        "detail",
                    "done":         done,
                    "total":        len(offsets),
                    "collected":    len(all_reviews),
                    "brand":        "명가삼대떡집",
                    "progress_pct": pct,
                    "progress_msg": f"명가삼대떡집 {len(all_reviews):,}/{total:,}건 수집 중... ({pct}%)",
                })

            await asyncio.sleep(0.05)   # 서버 부하 최소화

    print(f"  [명가삼대떡집] 최종 {len(all_reviews):,}건 완료")
    return all_reviews


async def collect_all(progress_cb=None) -> dict:
    print("=" * 50)
    print(f"수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"방식: vreview API 직접 호출 (병렬 {CONCURRENT}개)")

    changeok_jasa = []   # 창억떡 추후 추가
    myeongga_jasa = await scrape_myeongga(progress_cb)

    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": {"jasa": changeok_jasa, "smartstore": []},
        "myeongga": {"jasa": myeongga_jasa, "smartstore": []},
    }

    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n완료! 총 {len(myeongga_jasa):,}건 → {DATA_PATH}")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())
