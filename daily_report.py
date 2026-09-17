"""Deterministic daily review digest; no LLM, network, or message sending."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
import re

KST = ZoneInfo('Asia/Seoul')
BRANDS = [('jasaol', '백년화편', '자사'), ('myeongga', '명가삼대떡집', '경쟁사')]
from review_selection import highlights, select_report
from review_identity import review_identity


def yesterday(clock=None):
    clock = clock or datetime.now(KST)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=KST)
    return (clock.astimezone(KST).date() - timedelta(days=1)).isoformat()


def score(row):
    try:
        value = float(row.get('score'))
        return value if math.isfinite(value) and 1 <= value <= 5 else None
    except (ValueError, TypeError):
        return None


def build_report(cache, target, naver_state=None, clock=None):
    # Reject invalid input rather than silently picking a different date.
    if datetime.strptime(target, '%Y-%m-%d').strftime('%Y-%m-%d') != target:
        raise ValueError('날짜 형식은 YYYY-MM-DD입니다.')
    clock = clock or datetime.now(KST)
    cards = []
    for key, name, role in BRANDS:
        source = cache.get(key, [])
        seen, rows = set(), []
        for row in source:
            if row.get('date') != target:
                continue
            ident = review_identity(row)
            if ident in seen:
                continue
            seen.add(ident)
            rows.append(row)
        latest = max((str(r.get('date', '')) for r in source), default='')
        unavailable = not source
        values = [score(r) for r in rows if score(r) is not None]
        low = [r for r in rows if score(r) is not None and score(r) <= 3]
        selected = []
        for row in rows:
            text = str(row.get('content') or '')
            selected.append({'score': score(row), 'product': str(row.get('product') or '상품명 미제공'),
                             'platform': str(row.get('platform') or '미분류'), 'excerpt': text,
                             'highlights': [], 'date':target})
        # All rows are retained; longest review bodies appear first.
        selected.sort(key=lambda r: len(r['excerpt']), reverse=True)
        if unavailable:
            coverage = '저장된 자료 없음 · 수집 상태 확인 필요'
        elif not latest or latest < target:
            coverage = '전일 자료 확인 필요 · 후기 없음으로 단정할 수 없음'
        else:
            coverage = '수집된 자료 기준 · 전체 후기 수집 여부 미확인'
        if key == 'jasaol' and (naver_state or {}).get('state') != 'ready':
            coverage = '네이버 자동 수집 미확인 · 수집된 자사몰/네이버 자료만 반영'
        cards.append({'key':key, 'name':name, 'role':role, 'available':not unavailable,
                      'count':len(rows) if not unavailable else None,
                      'average':round(sum(values)/len(values), 2) if values else None,
                      'rated_count':len(values), 'low_count':len(low) if not unavailable else None,
                      'latest_review_date':latest or None, 'coverage':coverage, 'reviews':selected})
    total = sum(c['count'] or 0 for c in cards)
    return {'schema_version':2, 'date': target, 'generated_at': clock.astimezone(KST).isoformat(), 'timezone':'Asia/Seoul',
            'total':total, 'low_count':sum(c['low_count'] or 0 for c in cards), 'brands':cards,
            'notice':'수집된 후기만 집계합니다. 미수집·지연 채널은 전체 수치에서 누락될 수 있습니다.',
            'selection_rule':'백년화편·명가삼대떡집의 저장된 전일 후기 전체 · 본문 생략 없음 · 글자 수 많은 순',
            'highlight_rule':''}


def report_dates(directory):
    """Only actual saved snapshots are listed; never fabricate past reports."""
    dates = []
    if directory.exists():
        for path in directory.glob('????-??-??.json'):
            try:
                valid_report_date(path.stem)
                dates.append(path.stem)
            except ValueError:
                continue
    return sorted(dates, reverse=True)


def valid_report_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('날짜 형식은 YYYY-MM-DD입니다.')
    datetime.strptime(value, '%Y-%m-%d')
    return value


def read_report(directory, day):
    import json
    valid_report_date(day)
    report = json.loads((directory / f'{day}.json').read_text(encoding='utf-8'))
    if report.get('date') != day:
        raise ValueError('저장된 보고서 날짜가 일치하지 않습니다.')
    return report
