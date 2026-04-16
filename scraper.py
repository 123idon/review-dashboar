import re
import json
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

DATA_PATH = Path("data/reviews.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def parse_date(s: str):
    if not s:
        return None
    s = s.strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y.%m.%d", "%y.%m.%d"]:
        try:
            d = datetime.strptime(s[:len(fmt.replace("%y","-").replace("%Y","----").replace("%m","--").replace("%d","--").replace("%H","--").replace("%M","--").replace("%S","--"))], fmt)
            if d.year < 2000:
                d = d.replace(year=d.year + 2000)
            return d
        except ValueError:
            continue
    # 간단 파싱
    for fmt in ["%y.%m.%d", "%Y.%m.%d", "%Y-%m-%d"]:
        try:
            d = datetime.strptime(s[:8] if len(s) >= 8 else s, fmt)
            if d.year < 2000:
                d = d.replace(year=d.year + 2000)
            return d
        except:
            continue
    return None


def detect_platform(author: str) -> str:
    if not author:
        return "direct"
    a = author.strip()
    if a.startswith("카"):
        return "kakao"
    if a.startswith("네"):
        return "naver"
    return "direct"


def clean_content(text: str) -> str:
    text = re.sub(r"\(\d{4}-\d{2}-\d{2}[^)]*등록된[^)]*\)", "", text)
    text = re.sub(r"\(브이리뷰[^)]*\)", "", text)
    return text.strip()


def parse_list_item(item) -> dict | None:
    """목록 페이지 li 태그에서 후기 파싱 (상세 페이지 불필요)"""
    try:
        # ── 별점 ──
        score = 0
        rate_el = item.select_one("[data-rate]")
        if rate_el:
            try:
                score = int(rate_el["data-rate"])
            except:
                pass
        if score == 0:
            # class="rate rateN" 에서 추출
            rate_wrap = item.select_one(".rate")
            if rate_wrap:
                m = re.search(r"rate(\d)", " ".join(rate_wrap.get("class", [])))
                if m:
                    score = int(m.group(1))
        # subject에서도 추출
        if score == 0:
            subj = item.select_one(".subject")
            if subj:
                txt = subj.get_text(strip=True)
                if "불만족" in txt:
                    score = 1
                elif "보통" in txt:
                    score = 3
                elif "만족" in txt:
                    score = 5

        # ── 내용 ──
        cont_el = item.select_one(".cont")
        content = clean_content(cont_el.get_text(separator=" ", strip=True)) if cont_el else ""
        # 네이버 페이 구매평 패턴 정리
        content = re.sub(r"\(\d{4}-\d{2}-\d{2}[^)]*네이버[^)]*\)", "", content).strip()
        content = content[:500]

        # ── 날짜 ──
        date_obj = None
        date_el = item.select_one(".date span")
        if date_el:
            date_text = date_el.get_text(strip=True)
            date_obj = parse_date(date_text)
        # 내용에서도 날짜 추출 시도
        if not date_obj:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", content)
            if m:
                date_obj = parse_date(m.group(1))

        # ── 상품명 ──
        product = ""
        prod_el = item.select_one(".prod_name .name a")
        if prod_el:
            product = prod_el.get_text(strip=True)
        # 대괄호 등 정리
        if len(product) > 80:
            product = product[:80]

        # ── 작성자 / 플랫폼 ──
        member_el = item.select_one(".member")
        author = member_el.get_text(strip=True) if member_el else ""

        return {
            "date": date_obj.strftime("%Y-%m-%d") if date_obj else datetime.now().strftime("%Y-%m-%d"),
            "score": score,
            "product": product,
            "title": "",
            "content": content,
            "platform": detect_platform(author),
            "author": author,
        }
    except Exception as e:
        print(f"  parse_list_item 오류: {e}")
        return None


async def scrape_list_pages(base_url: str, list_path: str, brand: str,
                             progress_cb=None) -> list:
    """목록 페이지만 긁어서 파싱 (상세 페이지 불필요 — 15배 빠름)"""
    reviews = []
    page = 1

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        while True:
            url = f"{base_url}{list_path}&page={page}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as e:
                print(f"  [{brand}] 페이지 {page} 요청 실패: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select("li[data-review-no]")

            if not items:
                print(f"  [{brand}] {page}페이지 종료 (총 {len(reviews)}건)")
                break

            for item in items:
                parsed = parse_list_item(item)
                if parsed:
                    reviews.append(parsed)

            print(f"  [{brand}] {page}페이지 → {len(items)}건 (누적 {len(reviews)}건)")

            if progress_cb:
                progress_cb({
                    "phase": "listing",
                    "page": page,
                    "total_so_far": len(reviews),
                    "brand": brand,
                })

            page += 1
            await asyncio.sleep(0.8)   # 서버 부하 방지

    print(f"  [{brand}] 최종 {len(reviews)}건 완료")
    return reviews


async def collect_all(progress_cb=None) -> dict:
    print("=" * 50)
    print(f"후기 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("※ 목록 페이지 직접 파싱 방식 (빠름)")

    print("\n[1/2] 창억떡 수집...")
    changeok_jasa = await scrape_list_pages(
        base_url="https://m.changeok.co.kr",
        list_path="/board/product/list.html?board_no=4",
        brand="창억",
        progress_cb=progress_cb,
    )

    print("\n[2/2] 명가삼대떡집 수집...")
    myeongga_jasa = await scrape_list_pages(
        base_url="https://myeonggashop.com",
        list_path="/board/review/list.html?board_no=4",
        brand="명가삼대떡집",
        progress_cb=progress_cb,
    )

    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": {"jasa": changeok_jasa, "smartstore": []},
        "myeongga": {"jasa": myeongga_jasa, "smartstore": []},
    }

    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = len(changeok_jasa) + len(myeongga_jasa)
    print(f"\n수집 완료! 총 {total}건 → {DATA_PATH}")
    return result


if __name__ == "__main__":
    asyncio.run(collect_all())
