import re
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DATA_PATH = Path("data/reviews.json")

# ────────────────────────────────────────────
# 공통 유틸
# ────────────────────────────────────────────

def parse_cafe24_date(s: str):
    s = s.strip()
    # 26.03.25  or  2026.03.25
    m = re.match(r"^(\d{2,4})\.(\d{2})\.(\d{2})$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def detect_platform_cafe24(author: str) -> str:
    """작성자 앞 글자로 플랫폼 추정 (Cafe24 자사몰)"""
    if not author:
        return "direct"
    prefix = author[0]
    if prefix == "카":
        return "kakao"
    if prefix == "네":
        return "naver"
    if prefix == "구":
        return "google"
    return "direct"


KOREAN_STOPWORDS = {
    "이", "가", "은", "는", "을", "를", "의", "도", "로", "으로",
    "에", "에서", "와", "과", "이고", "고", "하고", "한", "하는",
    "있는", "없는", "있어요", "없어요", "해요", "합니다", "했어요",
    "있습니다", "없습니다", "그", "이것", "저", "제", "너무", "정말",
    "진짜", "완전", "아주", "매우", "좀", "좋은", "좋아요", "좋고",
    "또", "다시", "번", "번째", "개", "개씩", "세트", "구매", "주문",
    "배송", "상품", "제품", "포장", "선물", "가격", "감사", "합니다",
    "했습니다", "드립니다", "드려요", "같아요", "같습니다", "것", "거",
    "때", "더", "수", "잘", "못", "안", "다", "안됩", "처음", "다음",
}

def extract_keywords(texts: list[str], top_n: int = 10) -> list[tuple[str, int]]:
    freq: dict[str, int] = {}
    for text in texts:
        words = re.findall(r"[가-힣]{2,6}", text)
        for w in words:
            if w not in KOREAN_STOPWORDS:
                freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: -x[1])[:top_n]


# ────────────────────────────────────────────
# Cafe24 자사몰 스크래퍼
# ────────────────────────────────────────────

def scrape_cafe24(base_url: str, board_no: int = 4, max_pages: int = 100) -> list[dict]:
    """Cafe24 리뷰 게시판 전체 수집"""
    reviews = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        url = f"{base_url}/board/product/list.html?board_no={board_no}&page={page}"
        try:
            resp = session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  [cafe24] 페이지 {page} 요청 실패: {e}")
            break

        rows = soup.select("table tbody tr")
        if not rows:
            break

        page_reviews = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # ── 날짜 추출 ──
            date_obj = None
            for cell in cells:
                d = parse_cafe24_date(cell.get_text(strip=True))
                if d:
                    date_obj = d
                    break
            if not date_obj:
                continue

            # ── 별점 추출 ──
            score = 0
            for cell in cells:
                m = re.search(r"(\d)점", cell.get_text())
                if m:
                    score = int(m.group(1))
                    break

            # ── 상품명 추출 ──
            product_name = ""
            for cell in cells:
                a = cell.find("a", href=re.compile(r"/product/"))
                if a:
                    product_name = a.get_text(strip=True)
                    break

            # ── 제목 & 게시글 URL 추출 ──
            title = ""
            article_url = ""
            for cell in cells:
                a = cell.find("a", href=re.compile(r"/article/"))
                if a:
                    href = a.get("href", "")
                    article_url = href if href.startswith("http") else base_url + href
                    raw_title = a.get_text(strip=True)
                    title = re.sub(r"\[(만족|불만족|보통|NEW)\]", "", raw_title).strip()
                    break

            # ── 작성자 / 플랫폼 ──
            author = ""
            for cell in cells:
                t = cell.get_text(strip=True)
                if re.match(r"^[가-힣]\*+$", t) or (re.match(r"^[가-힣]{2,5}$", t) and len(t) <= 5):
                    author = t
                    break
            platform = detect_platform_cafe24(author)

            page_reviews.append({
                "date": date_obj.strftime("%Y-%m-%d"),
                "score": score,
                "product": product_name,
                "title": title,
                "content": "",          # 개별 페이지 방문 없이 빈값
                "platform": platform,
                "author": author,
                "article_url": article_url,
            })

        if not page_reviews:
            break

        reviews.extend(page_reviews)
        print(f"  [cafe24] {base_url} 페이지 {page} → {len(page_reviews)}건 수집")

    return reviews


def fetch_cafe24_content(review: dict) -> str:
    """개별 리뷰 페이지에서 본문 가져오기"""
    if not review.get("article_url"):
        return ""
    try:
        resp = requests.get(review["article_url"], headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        # Cafe24 리뷰 본문 셀렉터 (스킨마다 다를 수 있음)
        content_area = (
            soup.select_one(".review_cont")
            or soup.select_one(".board_view_content")
            or soup.select_one(".cont_area")
            or soup.select_one("td.board_view")
        )
        if content_area:
            return content_area.get_text(separator=" ", strip=True)
    except Exception:
        pass
    return ""


# ────────────────────────────────────────────
# 네이버 브랜드스토어 스크래퍼 (Playwright)
# ────────────────────────────────────────────

async def scrape_naver_store(store_name: str) -> list[dict]:
    """네이버 브랜드스토어 리뷰 수집 (Playwright + API 인터셉트)"""
    captured: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = await ctx.new_page()

        # ── 리뷰 API 응답 인터셉트 ──
        async def on_response(resp):
            url = resp.url
            if resp.status != 200:
                return
            review_patterns = [
                "paged-reviews", "reviewList", "/reviews?",
                "productReviews", "review/list",
            ]
            if not any(p in url for p in review_patterns):
                return
            try:
                data = await resp.json()
                items = (
                    data.get("contents")
                    or data.get("reviewList")
                    or data.get("reviews")
                    or (data.get("data") or {}).get("reviewList")
                    or []
                )
                for r in items:
                    date_raw = (
                        r.get("createDate") or r.get("reviewDate")
                        or r.get("createDt") or r.get("registeredDate") or ""
                    )
                    date_str = str(date_raw)[:10]
                    try:
                        datetime.strptime(date_str, "%Y-%m-%d")
                    except ValueError:
                        continue

                    score = int(
                        r.get("reviewScore") or r.get("starRating")
                        or r.get("score") or 0
                    )
                    captured.append({
                        "date": date_str,
                        "score": score,
                        "product": (
                            r.get("productName") or r.get("productTitle")
                            or r.get("itemName") or ""
                        ),
                        "title": "",
                        "content": (
                            r.get("reviewContent") or r.get("content")
                            or r.get("body") or ""
                        ),
                        "platform": "smartstore",
                        "author": str(
                            r.get("writerMemberId") or r.get("author") or ""
                        )[:3] + "****",
                    })
            except Exception:
                pass

        page.on("response", on_response)

        # ── 스토어 메인 → 전체 상품 목록 ──
        store_url = f"https://brand.naver.com/{store_name}/category/ALL"
        print(f"  [naver] {store_url} 접속 중...")
        try:
            await page.goto(store_url, wait_until="networkidle", timeout=40000)
        except Exception as e:
            print(f"  [naver] 접속 실패: {e}")
            await browser.close()
            return []

        await page.wait_for_timeout(2000)

        # 상품 URL 추출 (최대 30개)
        product_urls: list[str] = await page.evaluate(
            """() => {
                const anchors = [...document.querySelectorAll('a[href]')];
                const hrefs = anchors
                    .map(a => a.href)
                    .filter(h => /brand\\.naver\\.com\\/[^/]+\\/products\\/\\d+/.test(h));
                return [...new Set(hrefs)].slice(0, 30);
            }"""
        )
        print(f"  [naver] 상품 {len(product_urls)}개 발견")

        # ── 상품별 리뷰 탭 클릭하여 API 트리거 ──
        for i, prod_url in enumerate(product_urls[:20]):
            try:
                await page.goto(prod_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)

                # 리뷰 탭 클릭 시도 (셀렉터 여러 가지 시도)
                for sel in [
                    "a[data-nclick*='review']",
                    "button:has-text('리뷰')",
                    "a:has-text('리뷰')",
                    "[class*='tab_']:has-text('리뷰')",
                ]:
                    tab = await page.query_selector(sel)
                    if tab:
                        await tab.click()
                        await page.wait_for_timeout(1500)
                        break

                # 스크롤로 추가 리뷰 로드
                for _ in range(2):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(800)

                print(f"  [naver] 상품 {i+1}/{len(product_urls[:20])} 완료")
            except Exception as e:
                print(f"  [naver] 상품 스킵: {e}")
                continue

        await browser.close()

    print(f"  [naver] {store_name} 총 {len(captured)}건 수집")
    return captured


# ────────────────────────────────────────────
# 전체 수집 진입점
# ────────────────────────────────────────────

async def collect_all() -> dict:
    print("=" * 50)
    print(f"후기 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Cafe24 자사몰 (동기)
    print("\n[1/4] 창억떡 자사몰 수집...")
    changeok_jasa = scrape_cafe24("https://changeok.co.kr", board_no=4)

    print("\n[2/4] 명가삼대떡집 자사몰 수집...")
    myeongga_jasa = scrape_cafe24("https://myeonggashop.com", board_no=4)

    # 네이버 브랜드스토어 (비동기)
    print("\n[3/4] 창억떡 스마트스토어 수집...")
    changeok_naver = await scrape_naver_store("changeok")

    print("\n[4/4] 명가삼대떡집 스마트스토어 수집...")
    myeongga_naver = await scrape_naver_store("myeongga")

    # 최근 30건 본문 보강 (자사몰)
    print("\n본문 보강 중 (최근 리뷰)...")
    for r in sorted(changeok_jasa, key=lambda x: x["date"], reverse=True)[:30]:
        if not r["content"]:
            r["content"] = fetch_cafe24_content(r)
    for r in sorted(myeongga_jasa, key=lambda x: x["date"], reverse=True)[:30]:
        if not r["content"]:
            r["content"] = fetch_cafe24_content(r)

    result = {
        "last_updated": datetime.now().isoformat(),
        "changeok": {
            "jasa": changeok_jasa,
            "smartstore": changeok_naver,
        },
        "myeongga": {
            "jasa": myeongga_jasa,
            "smartstore": myeongga_naver,
        },
    }

    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = (
        len(changeok_jasa) + len(changeok_naver)
        + len(myeongga_jasa) + len(myeongga_naver)
    )
    print(f"\n수집 완료! 총 {total}건 → {DATA_PATH}")
    return result


def run_collect():
    """동기 래퍼 (scheduler에서 사용)"""
    asyncio.run(collect_all())


if __name__ == "__main__":
    asyncio.run(collect_all())
