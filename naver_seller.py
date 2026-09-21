"""Seller UI reader and disabled-by-default, short-lived server login console."""
import asyncio
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
import naver_automation as state
from smartstore_import import validate_reviews

router = APIRouter()
AUTH = state.DATA / 'naver_private' / 'seller-state.json'
LOCK = asyncio.Lock()
SESSION = {}
PROGRESS = {}
ROW_JS = r"""() => Array.from(document.querySelectorAll('[role="row"][row-index]')).map(e=>{
 const cell=k=>e.querySelector('[col-id="'+k+'"]');const txt=k=>cell(k)?.textContent.trim()||'';
 const id=cell('reviewContent')?.querySelector('a')?.getAttribute('ng-click')?.match(/openReviewDetailModal\((\d+)/)?.[1];
 return id?{row_index:Number(e.getAttribute('row-index')),review_no:id,product_no:txt('productNo'),product:txt('productName'),score:Number(txt('reviewScore')),
 content:txt('reviewContent'),author:txt('writerId'),date:txt('createDate').slice(0,10).replaceAll('.','-'),
 review_type:txt('reviewType'),platform:'naver',title:''}:null}).filter(Boolean)"""

def authorize(token):
    expected=os.environ.get('NAVER_SELLER_CONNECT_SHA256','')
    try: expires=float(os.environ.get('NAVER_SELLER_CONNECT_EXPIRES','0'))
    except ValueError: expires=0
    if not expected or time.time()>=expires or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),expected):
        raise HTTPException(403,'연결 화면이 비활성화됐거나 연결 시간이 만료됐습니다.')

def complete_single_page(rows, height, row_height):
    if row_height <= 0 or height <= 0 or abs(height / row_height - round(height / row_height)) > 0.001:
        return False
    count = round(height / row_height)
    return len(rows) == count and {r.get('row_index') for r in rows} == set(range(count))

async def close_session():
    browser=SESSION.pop('browser',None)
    pw=SESSION.pop('pw',None)
    SESSION.clear()
    if browser: await browser.close()
    if pw: await pw.stop()

async def read_rows(page, since=None):
    import re
    PROGRESS['stage'] = '리뷰 화면 이동'
    await page.goto('https://sell.smartstore.naver.com/#/review/search',wait_until='domcontentloaded')
    # The first seller landing can redirect a deep link to home after sign-in.
    await page.locator('#seller-lnb').wait_for(timeout=30000)
    if '/review/search' not in page.url:
        await page.goto('https://sell.smartstore.naver.com/#/review/search',wait_until='domcontentloaded')
    await page.get_by_role('heading',name='리뷰관리',exact=True).wait_for(timeout=30000)
    if '백년화편' not in await page.locator('#seller-lnb').inner_text():
        raise ValueError('대상 판매자 확인 실패')
    guide_close=page.locator('#seller-rnb').get_by_role('button',name='닫기',exact=True)
    if await guide_close.count() and await guide_close.is_visible():
        await guide_close.click()
    PROGRESS['stage'] = '조회 조건 설정'
    await page.get_by_role('button',name='오늘',exact=True).click()
    yesterday = datetime.now(state.KST).date() - timedelta(days=1)
    if since:
        yesterday = datetime.fromisoformat(since).date()   # 조회 시작일(변수명은 호환 유지)
    start_input = page.locator('input[title="날짜 입력"]').nth(0)
    # Enable the displayed date input for normal input/change events.
    # No framework state or private API access is used.
    await start_input.evaluate('(e)=>e.removeAttribute("readonly")')
    await start_input.fill(yesterday.strftime('%Y.%m.%d.'))
    await start_input.press('Tab')
    if await start_input.input_value() != yesterday.strftime('%Y.%m.%d.'):
        raise ValueError('전일 날짜 설정 확인 실패')
    await page.get_by_role('button',name='검색',exact=True).click()
    await page.wait_for_timeout(4000)
    heading=await page.get_by_role('heading',name=re.compile('리뷰목록')).inner_text()
    match=re.search(r'총\s*([\d,]+)\s*개',heading)
    if not match: raise ValueError('조회 건수 확인 실패')
    expected=int(match.group(1).replace(',',''))
    if expected>10000: raise ValueError('조회 한도 초과')
    found={}
    PROGRESS['stage'] = '후기 목록 읽기'
    for _ in range(500):
        viewport=page.locator('.ag-body-viewport')
        if expected == 0: return [], {'expected':0,'source':'seller_ui'}
        await viewport.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await viewport.evaluate('(e)=>{e.scrollTop=0}')
        await page.wait_for_timeout(300)
        for _ in range(600):
            for row in await page.evaluate(ROW_JS): found[row['review_no']]=row
            if len(found)>=expected: break
            at_end=await viewport.evaluate('(e)=>e.scrollTop+e.clientHeight>=e.scrollHeight-2')
            if at_end: break
            await viewport.evaluate('(e)=>{e.scrollTop+=Math.max(100,e.clientHeight*0.8)}')
            await page.wait_for_timeout(250)
        if len(found)>=expected: break
        PROGRESS['stage'] = f'페이지 이동 요소 확인 ({len(found)}/{expected})'
        next_button=page.locator('[aria-label="다음 페이지로 이동"]').filter(visible=True)
        if await next_button.count()==0 or not await next_button.is_enabled(): break
        PROGRESS['stage'] = f'다음 페이지 갱신 대기 ({len(found)}/{expected})'
        await next_button.click()
        await viewport.scroll_into_view_if_needed()
        await viewport.evaluate('(e)=>{e.scrollTop=0}')
        for attempt in range(60):
            await page.wait_for_timeout(500)
            incoming = await page.evaluate(ROW_JS)
            if any(row['review_no'] not in found for row in incoming): break
        else: raise ValueError('다음 페이지에 새 후기가 표시되지 않음')
    final_heading = await page.get_by_role('heading',name=re.compile('리뷰목록')).inner_text()
    final_match = re.search(r'총\s*([\d,]+)\s*개',final_heading)
    if final_match:
        expected = int(final_match.group(1).replace(',',''))
    reported_total = expected
    if len(found) != expected:
        # Seller's heading can retain the previous query total. Only accept a
        # single-page grid when every geometric row slot has a unique review.
        geometry = await page.locator('.ag-body-viewport').evaluate('''e=>({
          height:e.scrollHeight,
          rowHeight:e.querySelector('[role="row"][row-index]')?.offsetHeight || 0
        })''')
        pages = page.locator('.pagination._pc_pagination li._page:not(.ag-paging-button)')
        if await pages.count() == 1 and complete_single_page(list(found.values()), geometry['height'], geometry['rowHeight']):
            expected = len(found)
    PROGRESS['stage'] = f'후기 건수 대조 ({len(found)}/{expected})'
    if len(found)!=expected: raise ValueError('조회 건수와 수집 건수 불일치')
    rows=list(found.values())
    PROGRESS['stage'] = '후기 형식 검증'
    if rows: validate_reviews(rows)
    if any(row['date'] < yesterday.isoformat() for row in rows):
        raise ValueError('조회 날짜 범위 불일치')
    for row in rows: row.pop('row_index',None)
    return rows, {'expected':expected,'reported_total':reported_total,'source':'seller_ui','date_from':yesterday.isoformat()}

async def read_rows_excel(page, since):
    """폴백: 리뷰관리 화면의 '엑셀 다운로드' → openpyxl 파싱. 버튼 문구·팝업은 화면 변경 시 조정."""
    import re
    from openpyxl import load_workbook
    start = datetime.fromisoformat(since).date() if since else datetime.now(state.KST).date() - timedelta(days=1)
    PROGRESS['stage'] = '엑셀 폴백: 화면 이동'
    await page.goto('https://sell.smartstore.naver.com/#/review/search',wait_until='domcontentloaded')
    await page.locator('#seller-lnb').wait_for(timeout=30000)
    if '/review/search' not in page.url:
        await page.goto('https://sell.smartstore.naver.com/#/review/search',wait_until='domcontentloaded')
    await page.get_by_role('heading',name='리뷰관리',exact=True).wait_for(timeout=30000)
    await page.get_by_role('button',name='오늘',exact=True).click()
    start_input = page.locator('input[title="날짜 입력"]').nth(0)
    await start_input.evaluate('(e)=>e.removeAttribute("readonly")')
    await start_input.fill(start.strftime('%Y.%m.%d.'))
    await start_input.press('Tab')
    await page.get_by_role('button',name='검색',exact=True).click()
    await page.wait_for_timeout(4000)
    btn = page.get_by_role('button', name=re.compile(r'엑셀\s*다운')).filter(visible=True)
    if await btn.count() == 0: raise ValueError('엑셀 다운로드 버튼 없음')
    PROGRESS['stage'] = '엑셀 폴백: 다운로드'
    async with page.expect_download(timeout=120000) as dl_info:
        await btn.first.click()
        for name in ('확인','다운로드'):
            ok = page.get_by_role('button', name=name, exact=True).filter(visible=True)
            try:
                if await ok.count(): await ok.first.click(timeout=3000)
            except Exception: pass
    dl = await dl_info.value
    path = state.DATA / 'naver_private' / 'seller_export.xlsx'
    path.parent.mkdir(parents=True, exist_ok=True)
    await dl.save_as(str(path))
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active; ws.reset_dimensions()
        it = iter(ws.iter_rows(values_only=True)); headers = next(it)
        idx = {str(v).strip(): i for i, v in enumerate(headers) if v is not None}
        need = ['리뷰등록일','구매자평점','상품명','리뷰상세내용','등록자','리뷰글번호']
        if not all(k in idx for k in need): raise ValueError('엑셀 열 구성 변경')
        out = []
        for row in it:
            if not any(v is not None for v in row): continue
            c = lambda k: row[idx[k]] if k in idx and idx[k] < len(row) else None
            raw = c('리뷰등록일')
            if isinstance(raw, datetime): d = raw.strftime('%Y-%m-%d')
            else:
                m = re.match(r'\s*(\d{4})[.\-/](\d{2})[.\-/](\d{2})', str(raw))
                if not m: raise ValueError('엑셀 날짜 형식 확인 불가')
                d = '-'.join(m.groups())
            if d < start.isoformat(): continue
            out.append(dict(date=d, score=float(c('구매자평점') or 0), product=str(c('상품명') or ''),
                            content=str(c('리뷰상세내용') or ''), author=str(c('등록자') or ''),
                            review_no=str(c('리뷰글번호') or ''), review_type=str(c('리뷰구분') or ''),
                            platform='naver', title=''))
    finally:
        wb.close()
        try: path.unlink()
        except OSError: pass
    if out: validate_reviews(out)
    return out, {'expected':len(out),'source':'seller_excel','date_from':start.isoformat()}

async def collect(since=None):
    if not AUTH.exists(): raise ValueError('서버 판매자 인증 없음')
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        try:
            context=await browser.new_context(storage_state=str(AUTH),locale='ko-KR',timezone_id='Asia/Seoul',viewport={'width':1440,'height':1000},accept_downloads=True)
            page=await context.new_page()
            try:
                rows,details=await read_rows(page, since)
            except Exception as first:
                # 로그인 자체가 풀린 경우는 폴백 의미 없음
                if 'nid.naver.com' in page.url: raise
                PROGRESS['stage'] = f'화면 읽기 실패({type(first).__name__}) → 엑셀 폴백'
                rows,details=await read_rows_excel(page, since)
                details['ui_error']=type(first).__name__
            # 매 실행마다 갱신된 쿠키를 다시 저장해 세션을 이어간다
            state.private_save(AUTH,await context.storage_state())
            return rows,details
        finally: await browser.close()

@router.post('/api/naver-seller/session')
async def upload_session(request:Request):
    """로컬 PC에서 로그인한 브라우저의 storage_state 를 서버에 이전. 토큰 env로만 잠깐 열린다."""
    authorize(request.headers.get('X-Naver-Connect',''))
    raw=await request.body()
    if len(raw)>2_000_000: raise HTTPException(413,'세션 파일이 너무 큽니다.')
    try:
        import json
        storage=json.loads(raw)
        assert isinstance(storage,dict) and isinstance(storage.get('cookies'),list)
    except Exception: raise HTTPException(400,'storage_state 형식 오류')
    if state.LOCK.locked(): raise HTTPException(409,'수집 중입니다. 잠시 후 다시 시도하세요.')
    from playwright.async_api import async_playwright
    async with LOCK:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
            try:
                context=await browser.new_context(storage_state=storage,locale='ko-KR',timezone_id='Asia/Seoul',viewport={'width':1440,'height':1000})
                page=await context.new_page()
                await page.goto('https://sell.smartstore.naver.com/',wait_until='domcontentloaded')
                try:
                    await page.locator('#seller-lnb').wait_for(timeout=30000)
                    ok='백년화편' in await page.locator('#seller-lnb').inner_text()
                except Exception: ok=False
                if not ok or 'nid.naver.com' in page.url:
                    raise HTTPException(409,'서버에서 세션 검증 실패 — 로그인이 유지되지 않습니다.')
                state.private_save(AUTH,await context.storage_state())
            finally: await browser.close()
    state.record('unverified','판매자 세션 이전 완료 · 첫 수집 대기',mode='seller',retry_at=0)
    from main import run_naver_collect
    asyncio.create_task(run_naver_collect())
    return {'ok':True,'message':'세션 저장 완료. 첫 수집을 시작합니다.'}

@router.get('/naver-seller-connect',response_class=HTMLResponse)
async def portal():
    return HTMLResponse(Path('static/naver-seller-connect.html').read_text(encoding='utf-8'),headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'})

@router.post('/api/naver-seller/connect')
async def control(request:Request):
    authorize(request.headers.get('X-Naver-Connect',''))
    # Reject cross-origin drive-by commands; tokens never travel in URLs or logs.
    origin=request.headers.get('origin')
    allowed_origins = {str(request.base_url).rstrip('/')}
    public_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if public_domain:
        allowed_origins.add('https://' + public_domain)
    if origin and origin.rstrip('/') not in allowed_origins:
        raise HTTPException(403,'다른 사이트에서 연결할 수 없습니다.')
    raw=await request.body()
    if len(raw)>12000: raise HTTPException(413,'입력이 너무 깁니다.')
    try:
        import json
        command=json.loads(raw)
    except Exception: raise HTTPException(400,'잘못된 입력')
    async with LOCK:
        action=command.get('action')
        if action=='close':
            await close_session()
            return {'ok':True}
        if action=='start':
            if state.LOCK.locked(): raise HTTPException(409,'수집 중입니다.')
            await close_session()
            from playwright.async_api import async_playwright
            pw=await async_playwright().start()
            browser=await pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
            context=await browser.new_context(storage_state=str(AUTH) if AUTH.exists() else None,locale='ko-KR',timezone_id='Asia/Seoul',viewport={'width':1440,'height':1000})
            page=await context.new_page()
            SESSION.update(pw=pw,browser=browser,context=context,page=page,expires=time.time()+900)
            async def expire():
                await asyncio.sleep(900)
                async with LOCK:
                    if SESSION.get('browser') is browser: await close_session()
            asyncio.create_task(expire())
            await page.goto('https://sell.smartstore.naver.com/',wait_until='domcontentloaded')
            return {'ok':True}
        if not SESSION or time.time()>SESSION['expires']:
            await close_session()
            raise HTTPException(410,'연결이 만료됐습니다. 다시 시작해 주세요.')
        context=SESSION['context']
        page=context.pages[-1] if context.pages else SESSION['page']
        if action=='image':
            return Response(await page.screenshot(type='jpeg',quality=75),media_type='image/jpeg',headers={'Cache-Control':'no-store'})
        if action=='diagnostics':
            return await page.evaluate("""() => ({
              headings:Array.from(document.querySelectorAll('h3')).map(e=>e.textContent),
              dates:Array.from(document.querySelectorAll('input[title="날짜 입력"]')).map(e=>e.value),
              rowCount:document.querySelectorAll('[role="row"][row-index]').length,
              columns:[...new Set(Array.from(document.querySelectorAll('[col-id]')).map(e=>e.getAttribute('col-id')))],
              handlers:Array.from(document.querySelectorAll('[col-id="reviewContent"] a')).slice(0,2).map(e=>e.getAttribute('ng-click')),
              pagination:Array.from(document.querySelectorAll('.pagination, [role="navigation"]')).map(e=>e.outerHTML).filter(s=>s.length<15000),
              grid:Array.from(document.querySelectorAll('.ag-body-viewport')).map(e=>({height:e.clientHeight,scrollHeight:e.scrollHeight,top:e.scrollTop}))
            })""")
        if action=='click':
            x,y=float(command.get('x',-1)),float(command.get('y',-1))
            if not (0<=x<=1440 and 0<=y<=1000): raise HTTPException(400,'좌표 오류')
            await page.mouse.click(x,y)
        elif action=='text':
            await page.keyboard.insert_text(str(command.get('text',''))[:2000])
        elif action=='key':
            key=command.get('key')
            if key not in ('Enter','Tab','Backspace','Control+A','Escape'): raise HTTPException(400,'지원하지 않는 키')
            await page.keyboard.press(key)
        elif action=='scroll': await page.mouse.wheel(0,max(-900,min(900,int(command.get('y',0)))))
        elif action=='save':
            try:
                # Approved server authentication can survive a collector fix;
                # it does not mark collection successful until all rows validate.
                PROGRESS['stage'] = '판매자 계정 확인'
                if '백년화편' not in await page.locator('#seller-lnb').inner_text(timeout=5000):
                    raise ValueError('대상 판매자 확인 실패')
                state.private_save(AUTH,await context.storage_state())
                state.record('unverified','서버 로그인 저장 · 후기 수집 검증 중',mode='seller',retry_at=0)
                rows,details=await read_rows(page)
                if not rows: raise ValueError('실제 후기 검증 필요')
                # Only a verified UI read permits persistent authentication storage.
                verified_auth = await context.storage_state()
                from uuid import uuid4
                from scraper import safe_save
                from main import smartstore_chunk_path, import_smartstore_done
                sid=uuid4().hex
                PROGRESS['stage'] = '후기 병합 저장'
                safe_save(smartstore_chunk_path(sid),rows)
                result=await import_smartstore_done(sid,len(rows))
                state.private_save(AUTH,verified_auth)
                state.record('ready','판매자 화면 수집 정상 · 매일 한국시간 00:00',mode='seller',last_success=state.now(),received=len(rows),retry_at=0,**details)
                from main import run_daily_report
                await run_daily_report()
                await close_session()
                return {'ok':True,'received':len(rows),'added':result['added']}
            except Exception as exc:
                # No credentials, page text or provider payloads in errors.
                stage=PROGRESS.get('stage','연결 확인')
                kind=type(exc).__name__
                message=f'서버 검증 중단: {stage} ({kind}). 로그인 정보는 표시하지 않습니다.'
                if AUTH.exists(): state.record('unverified',message,mode='seller',retry_at=0)
                raise HTTPException(409,message)
        else: raise HTTPException(400,'지원하지 않는 명령')
        return {'ok':True}
