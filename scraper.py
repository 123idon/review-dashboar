import re
import json
import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

DATA_PATH = Path("data/reviews.json")
CONCURRENT = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def parse_date(s: str):
    s = s.strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y.%m.%d", "%y.%m.%d"]:
        try:
            d = datetime.strptime(s[:19] if len(s) >= 19 else s[:10], fmt)
            if d.year < 2000:
                d = d.replace(year=d.year + 2000)
            return d
        except ValueError:
            continue
    return None


def detect_platform(author: str) -> str:
    if not author:
        return "direct"
    if "카" in author[:2]:
        return "kakao"
    if "네" in author[:2]:
        return "naver"
    return "direct"


def clean_content(text: str) -> str:
    text = re.sub(r"\(\d{4}-\d{2}-\d{2}[^)]*등록된[^)]*\)", "", text)
    text = re.sub(r"\(브이리뷰[^)]*\)", "", text)
    return text.strip()


def parse_review_text(text: str, brand: str = "") -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    product = ""
    for i, line in enumerate(lines):
        if re.match(r"[\d,]+원", line) and i > 0:
            candidate = lines[i - 1]
            if (len(candidate) > 4
                    and "rights" not in candidate.lower()
                    and "reserved" not in candidate.lower()
                    and not re.match(r"\d", candidate)):
                product = candidate.strip()
            break

    score = 0
    for line in lines[:20]:
        if line == "불만족":
            score = 1
            break
        if line == "보통":
            score = 3
            break
        if line == "만족":
            score = 5
            break
    if score == 0:
        m = re.search(r"(\d)점", text[:400])
        if m:
            score = int(m.group(1))

    author = ""
    m = re.search(r"([가-힣a-zA-Z]\*+)\s*(?:\(ip|\d{4}-)", text)
    if m:
        author = m.group(1)

    date_obj = None
    author_line_m = re.search(r"[가-힣a-zA-Z]\*+\s*(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}:\d{2})", text)
    if author_line_m:
        date_obj = parse_date(author_line_m.group(1))
    if not date_obj:
        m = re.search(r"\((\d{4}-\d{2}-\d{2})[^)]*등록된", text)
        if m:
            date_obj = parse_date(m.group(1))
    if not date_obj:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if m:
            date_obj = parse_date(m.group(1))

    author_passed = False
    content_lines = []
    for line in lines:
        if re.match(r"[가-힣a-zA-Z]\*+\s*\d{4}-", line) or re.match(r"[가-힣a-zA-Z]\*+\s*\(ip", line):
            author_passed = True
            continue
        if author_passed:
            if re.match(r"삭제|수정|목록|추천|신고|이전글|다음글|관련|번호|상품명|작성자|회원에게|copyright|All rights", line, re.IGNORECASE):
                break
            if re.match(r"\d{5,}", line):
                break
            line = clean_content(line)
            if len(line) > 2:
                content_lines.append(line)
        if len(content_lines) >= 5:
            break
    content = clean_content(" ".join(content_lines))[:500]

    return {
        "date": date_obj.strftime("%Y-%m-%d") if date_obj else datetime.now().strftime("%Y-%m-%d"),
        "score": score,
        "product": product,
        "title": "",
        "content": content,
        "platform": detect_platform(author),
        "author": author,
    }


async def fetch_review_pw(context, url: str, brand: str, semaphore):
    async with semaphore:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(500)
            text = await page.evaluate("() => document.body.innerText")
            return parse_review_text(text, brand)
        except Exception:
            return None
        finally:
            await page.close()


async def get_review_nos(context, base_url: str, list_path: str, max_pages: int = 9999):
    review_nos = []
    page = await context.new_page()
    try:
        for p in range(1, max_pages + 1):
            url = f"{base_url}{list_path}&page={p}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                nos = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('li[data-review-no]'))
                              .map(i => i.getAttribute('data-review-no'))
                              .filter(Boolean)
                """)
                if not nos:
                    print(f"  목록 {p}페이지 종료 (총 {len(review_nos)}건)")
                    break
                review_nos.extend(nos)
                print(f"  목록 {p}페이지 → {len(nos)}건")
            except Exception as e:
                print(f"  목록 {p}페이지 실패: {e}")
                break
    finally:
        await page.close()
    return review_nos


async def scrape_site(base_url, list_path, article_path, brand, max_pages=9999):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="ko-KR",
            extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        print(f"  [{brand}] 목록 수집 중...")
        nos = await get_review_nos(context, base_url, list_path, max_pages)
        print(f"  [{brand}] 총 {len(nos)}건 → 상세 수집 시작")

        if not nos:
            await browser.close()
            return []

        semaphore = asyncio.Semaphore(CONCURRENT)
        urls = [f"{base_url}{article_path}/{no}/" for no in nos]
        tasks = [fetch_review_pw(context, url, brand, semaphore) for url in urls]

        reviews = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                reviews.append(result)
            done += 1
            if done % 50 == 0:
                print(f"  [{brand}] {done}/{len(urls)} 완료 ({len(reviews)}건)")

        await browser.close()
        print(f"  [{brand}] 최종 {len(reviews)}건 완료")
        return reviews


async def collect_all() -> dict:
    print("=" * 50)
    print(f"후기 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n[1/2] 창억떡 수집...")
    changeok_jasa = await scrape_site(
        base_url="https://m.changeok.co.kr",
        list_path="/board/product/list.html?board_no=4",
        article_path="/article/구매후기/4",
        brand="창억",
        max_pages=9999,
    )

    print("\n[2/2] 명가삼대떡집 수집...")
    myeongga_jasa = await scrape_site(
        base_url="https://myeonggashop.com",
        list_path="/board/review/list.html?board_no=4",
        article_path="/article/상품-사용후기/4",
        brand="명가삼대떡집",
        max_pages=9999,
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