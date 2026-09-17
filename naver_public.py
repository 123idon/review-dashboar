"""Anonymous, sequential collection through the public store UI.

Only observes responses made by the page itself. No private API URL, account,
proxy rotation, fingerprint spoofing or CAPTCHA handling is used.
"""
import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
import re
import time
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

from smartstore_import import validate_reviews

STORE = 'https://brand.naver.com/100yearshop'
CATALOG = STORE + '/category/1c533c275c734fa1af5487f242591ef8?cp=1'
PRODUCT_RE = re.compile(r'^/100yearshop/products/(\d+)/?$')


class CollectionStopped(Exception):
    def __init__(self, state, message, retry_at=None):
        super().__init__(message)
        self.state, self.retry_at = state, retry_at


def retry_deadline(value='', clock=None):
    clock = time.time() if clock is None else clock
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - clock
        except (ValueError, TypeError, OverflowError):
            delay = 0
    return clock + max(86400, delay)  # Persist through restarts; never retry in the same run.


def product_link(href):
    url = urlparse(urljoin(STORE, href or ''))
    if url.scheme != 'https' or url.hostname != 'brand.naver.com':
        return None
    match = PRODUCT_RE.fullmatch(url.path)
    return (match.group(1), 'https://brand.naver.com' + url.path.rstrip('/')) if match else None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def decode_reviews(payload, product_id, product_name, source_url):
    """Strict adapter: reject unknown layouts, never synthesize dates or ratings."""
    rows = []
    for obj in walk(payload):
        if not {'reviewContent', 'reviewScore', 'reviewId', 'createDate'} <= obj.keys():
            continue
        identity = obj.get('productNo') or obj.get('productId')
        if identity is None or str(identity) != str(product_id):
            continue
        raw = str(obj['createDate'])
        try:
            instant = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if instant.tzinfo is not None:
                instant = instant.astimezone(ZoneInfo('Asia/Seoul'))
            date = instant.date().isoformat()
        except ValueError:
            raise CollectionStopped('layout_changed', '공개 후기 날짜 형식을 확인하지 못했습니다.')
        author = obj.get('writerMemberId') or obj.get('writerId') or ''
        # Public pages should mask identifiers; do not add unmasked identifiers to the dashboard.
        author = str(author)
        if author and '*' not in author:
            author = author[:2] + '***'
        row = dict(platform='naver', date=date, score=obj['reviewScore'],
                   content=obj['reviewContent'], review_no=str(obj['reviewId']),
                   author=author, product=product_name, title='', product_no=str(product_id),
                   source_url=source_url)
        if not obj['reviewId']:
            raise CollectionStopped('layout_changed', '공개 후기 번호를 확인하지 못했습니다.')
        try:
            rows.extend(validate_reviews([row]))
        except ValueError:
            raise CollectionStopped('layout_changed', '공개 후기 필수 항목이 변경되었습니다.') from None
    return rows


def observed_total(payload):
    if not isinstance(payload, dict):
        return None
    for key in ('totalElements', 'totalCount'):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    for key in ('data', 'result'):
        if key in payload:
            value = observed_total(payload[key])
            if value is not None:
                return value
    return None


async def collect(since_date):
    import httpx

    # Respect robots rules before opening the store; errors are not treated as permission.
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.get('https://brand.naver.com/robots.txt', headers={'User-Agent': 'ReviewDashboard/1.0'})
    if response.status_code in (401, 403, 429):
        raise CollectionStopped('blocked', f'공개 페이지 접근 제한(HTTP {response.status_code}). 자동 재시도를 보류합니다.',
                                retry_deadline(response.headers.get('Retry-After', '')))
    if response.status_code != 200:
        raise CollectionStopped('unverified', '공개 사이트의 수집 허용 범위를 확인하지 못했습니다.')
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    if not robots.can_fetch('ReviewDashboard', CATALOG):
        raise CollectionStopped('not_allowed', '사이트 robots.txt가 이 경로의 자동 수집을 허용하지 않습니다.')

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
        context = await browser.new_context(locale='ko-KR', timezone_id='Asia/Seoul')
        page = await context.new_page()
        page.set_default_timeout(20000)
        stopped = []
        tasks = set()
        payloads = []

        async def route_request(route):
            host = urlparse(route.request.url).hostname or ''
            parsed = urlparse(route.request.url)
            if (parsed.hostname == 'brand.naver.com'
                    and route.request.resource_type in ('document', 'xhr', 'fetch')
                    and not robots.can_fetch('ReviewDashboard', route.request.url)):
                stopped.append(CollectionStopped('not_allowed', '사이트가 요청 경로의 자동 수집을 허용하지 않습니다.'))
            if stopped or host == 'nid.naver.com' or host == 'sell.smartstore.naver.com':
                await route.abort()
            else:
                await route.continue_()

        async def observe(response):
            parsed = urlparse(response.url)
            if parsed.hostname != 'brand.naver.com':
                return
            if response.status in (401, 403, 429) and response.request.resource_type in ('document', 'xhr', 'fetch'):
                stopped.append(CollectionStopped('blocked', f'공개 페이지 접근 제한(HTTP {response.status}). 자동 재시도를 보류합니다.',
                                                  retry_deadline(response.headers.get('retry-after', ''))))
                return
            if 'review' in parsed.path.lower() and 'application/json' in response.headers.get('content-type', ''):
                try:
                    payloads.append(await response.json())
                except Exception:
                    pass

        def on_response(response):
            task = asyncio.create_task(observe(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        async def settle():
            await asyncio.sleep(max(3, robots.crawl_delay('ReviewDashboard') or 0))
            if tasks:
                await asyncio.gather(*list(tasks))
            if stopped:
                raise stopped[0]
            text = await page.locator('body').inner_text()
            if any(s in text for s in ('비정상적인 접근', '접근이 제한', '자동입력 방지', '서비스 접속이 불가')):
                raise CollectionStopped('blocked', '공개 화면에서 접근 제한을 감지했습니다.', retry_deadline())
            return text

        async def visible_control(pattern):
            for role in ('link', 'button', 'tab'):
                options = page.get_by_role(role, name=pattern)
                for i in range(await options.count()):
                    node = options.nth(i)
                    if await node.is_visible() and await node.is_enabled() and await node.get_attribute('aria-disabled') != 'true':
                        return node
            return None

        await context.route('**/*', route_request)
        page.on('response', on_response)
        try:
            await page.goto(CATALOG, wait_until='domcontentloaded', timeout=45000)
            text = await settle()
            if '백년화편' not in text:
                raise CollectionStopped('layout_changed', '백년화편 공개 스토어인지 확인하지 못했습니다.')
            count = re.search(r'전체\s*상품\s*[\(\[]?\s*([\d,]+)', text)
            if not count:
                raise CollectionStopped('unverified', '전체 상품 건수를 확인하지 못해 완전 수집으로 처리하지 않습니다.')
            expected = int(count.group(1).replace(',', ''))
            products = {}
            for _ in range(50):
                for href in await page.locator('a[href]').evaluate_all('(nodes) => nodes.map(n => n.href)'):
                    link = product_link(href)
                    if link:
                        products[link[0]] = link[1]
                if len(products) >= expected:
                    break
                next_page = await visible_control(re.compile(r'^다음(?:\s*페이지)?$'))
                if next_page is None:
                    break
                await next_page.click()
                await settle()
                # A hard iteration cap and final count verification prevent silent truncation.
            if expected == 0 or len(products) != expected:
                raise CollectionStopped('partial', f'전체 상품 {expected}개 중 {len(products)}개 확인. 기존 후기는 유지합니다.')
            all_rows = {}
            for product_id, url in products.items():
                if not robots.can_fetch('ReviewDashboard', url):
                    raise CollectionStopped('not_allowed', '상품 후기 경로의 자동 수집이 허용되지 않습니다.')
                payloads.clear()
                await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                await settle()
                product_name = await page.title()
                tab = await visible_control(re.compile(r'^리뷰(?:\s|\(|\d|$)'))
                if tab is None:
                    raise CollectionStopped('layout_changed', '상품의 공개 리뷰 탭을 찾지 못했습니다.')
                await tab.click()
                await settle()
                latest = await visible_control(re.compile(r'^최신순$'))
                if latest is None:
                    raise CollectionStopped('layout_changed', '최신순 리뷰 정렬을 확인하지 못했습니다.')
                payloads.clear()
                await latest.click()
                await settle()
                seen = {}
                complete = False
                for _ in range(200):
                    batch, total = [], None
                    for payload in payloads:
                        decoded = decode_reviews(payload, product_id, product_name, url)
                        if decoded:
                            batch.extend(decoded)
                            total = observed_total(payload)
                    payloads.clear()
                    if not batch:
                        raise CollectionStopped('layout_changed', '공개 리뷰 응답 형식을 확인하지 못했습니다. 후기 0건으로 처리하지 않습니다.')
                    dates = [r['date'] for r in batch]
                    if dates != sorted(dates, reverse=True):
                        raise CollectionStopped('unverified', '최신순 정렬을 검증하지 못했습니다.')
                    before = len(seen)
                    for row in batch:
                        seen[row['review_no']] = row
                        if row['date'] >= since_date:
                            all_rows[row['review_no']] = row
                    if min(dates) < since_date or (total is not None and len(seen) >= total):
                        complete = True
                        break
                    if len(seen) == before:
                        break
                    next_page = await visible_control(re.compile(r'^다음(?:\s*페이지)?$'))
                    if next_page is None:
                        break
                    await next_page.click()
                    await settle()
                if not complete:
                    raise CollectionStopped('partial', '상품 리뷰의 수집 완료 여부를 확인하지 못했습니다. 기존 후기는 유지합니다.')
            return list(all_rows.values()), {'products_checked': len(products), 'since_date': since_date}
        finally:
            await context.close()
            if tasks:
                await asyncio.gather(*list(tasks), return_exceptions=True)
            await browser.close()
