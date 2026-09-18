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
 return id?{review_no:id,product_no:txt('productNo'),product:txt('productName'),score:Number(txt('reviewScore')),
 content:txt('reviewContent'),author:txt('writerId'),date:txt('createDate').slice(0,10).replaceAll('.','-'),
 review_type:txt('reviewType'),platform:'naver',title:''}:null}).filter(Boolean)"""

def authorize(token):
    expected=os.environ.get('NAVER_SELLER_CONNECT_SHA256','')
    try: expires=float(os.environ.get('NAVER_SELLER_CONNECT_EXPIRES','0'))
    except ValueError: expires=0
    if not expected or time.time()>=expires or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),expected):
        raise HTTPException(403,'연결 화면이 비활성화됐거나 연결 시간이 만료됐습니다.')

async def close_session():
    browser=SESSION.pop('browser',None)
    pw=SESSION.pop('pw',None)
    SESSION.clear()
    if browser: await browser.close()
    if pw: await pw.stop()

async def read_rows(page):
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
    PROGRESS['stage'] = f'후기 건수 대조 ({len(found)}/{expected})'
    if len(found)!=expected: raise ValueError('조회 건수와 수집 건수 불일치')
    rows=list(found.values())
    PROGRESS['stage'] = '후기 형식 검증'
    if rows: validate_reviews(rows)
    if any(row['date'] < yesterday.isoformat() for row in rows):
        raise ValueError('조회 날짜 범위 불일치')
    return rows, {'expected':expected,'source':'seller_ui','date_from':yesterday.isoformat()}

async def collect():
    if not AUTH.exists(): raise ValueError('서버 판매자 인증 없음')
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        try:
            context=await browser.new_context(storage_state=str(AUTH),locale='ko-KR',timezone_id='Asia/Seoul',viewport={'width':1440,'height':1000})
            page=await context.new_page()
            rows,details=await read_rows(page)
            state.private_save(AUTH,await context.storage_state())
            return rows,details
        finally: await browser.close()

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
