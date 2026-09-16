"""Status and offline import helpers for the anonymous public-review worker."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import time
from zoneinfo import ZoneInfo

from smartstore_import import validate_reviews

KST = ZoneInfo('Asia/Seoul')
DATA = Path(os.environ.get('NAVER_DATA_DIR', 'data'))
AUTH = DATA / 'naver_private' / 'state.json'
STATUS = DATA / 'naver_automation_status.json'
LOCK = asyncio.Lock()


def now():
    return datetime.now(KST).isoformat()


def private_save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(name, path)
        path.chmod(0o600)
    finally:
        Path(name).unlink(missing_ok=True)


def status():
    try:
        result = json.loads(STATUS.read_text(encoding='utf-8'))
        if result.get('mode') != 'public':
            result = {}
    except (OSError, ValueError):
        result = {}
    result.setdefault('state', 'pending')
    result.setdefault('message', '공개 후기 수집기 준비 · 실제 수집은 아직 검증되지 않았습니다.')
    result.update(mode='public', account_required=False, schedule='매일 00:00',
                  timezone='Asia/Seoul', gpt_tokens=0, session_configured=False,
                  running=LOCK.locked())
    retry_at = max(float(os.environ.get('NAVER_PUBLIC_NOT_BEFORE', '0')),
                   float(result.get('retry_at') or 0))
    if retry_at > time.time() and not LOCK.locked():
        result.update(state='cooldown', retry_at=retry_at,
                      retry_after=datetime.fromtimestamp(retry_at, KST).isoformat(),
                      message='공개 페이지 접근 제한으로 요청을 보류 중입니다. 네이버 계정은 사용하지 않습니다.')
    elif result.get('state') == 'running' and not LOCK.locked():
        result.update(state='interrupted', message='이전 공개 후기 수집이 서버 재시작으로 중단되었습니다.')
    return result


def record(state, message, **extra):
    old = status()
    old.update(state=state, message=message, checked_at=now(), **extra)
    private_save(STATUS, old)


def parse_export(path):
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows(values_only=True))
        headers = next(rows)
        index = {str(v).strip(): i for i, v in enumerate(headers) if v is not None}
        required = ['리뷰등록일', '구매자평점', '상품명', '리뷰상세내용', '등록자', '리뷰글번호']
        if not all(k in index for k in required):
            raise ValueError('판매자센터 리뷰 엑셀 열이 변경되었습니다.')
        out = []
        for row in rows:
            if not any(v is not None for v in row):
                continue
            def cell(key):
                i = index.get(key)
                return row[i] if i is not None and i < len(row) else None
            raw_date = cell('리뷰등록일')
            if isinstance(raw_date, datetime):
                date = raw_date.strftime('%Y-%m-%d')
            else:
                match = re.match(r'\s*(\d{4})[.\-/](\d{2})[.\-/](\d{2})', str(raw_date))
                if not match:
                    raise ValueError('리뷰 날짜 형식을 확인할 수 없습니다.')
                date = '-'.join(match.groups())
            out.append(dict(date=date, score=cell('구매자평점'), product=str(cell('상품명') or ''),
                            content=str(cell('리뷰상세내용') or ''), author=str(cell('등록자') or ''),
                            review_no=str(cell('리뷰글번호') or ''), review_type=str(cell('리뷰구분') or ''),
                            platform='naver', title=''))
        return validate_reviews(out)
    finally:
        workbook.close()
