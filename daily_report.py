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


def report_period(target):
    """The Sunday anchor is the Friday-Sunday digest viewed on Monday (KST)."""
    valid_report_date(target)
    end = datetime.strptime(target, '%Y-%m-%d').date()
    start = end - timedelta(days=2) if end.weekday() == 6 else end
    return {'date_from': start.isoformat(), 'date_to': target,
            'period_days': (end - start).days + 1}


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
    period = report_period(target)
    cards = []
    for key, name, role in BRANDS:
        source = cache.get(key, [])
        seen, rows = set(), []
        for row in source:
            if not period['date_from'] <= str(row.get('date') or '') <= target:
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
                             'highlights': [], 'date':row['date']})
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
    return {'schema_version':3, 'date': target, **period, 'generated_at': clock.astimezone(KST).isoformat(), 'timezone':'Asia/Seoul',
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


def statistics(report):
    """Count full stored daily rows, never only the display selection. No API."""
    from collections import Counter
    def aggregate(rows, available=True):
        values = [score(r) for r in rows if score(r) is not None]
        low = sum(v <= 3 for v in values)
        platforms = Counter('네이버' if r.get('platform') in ('naver', 'smartstore')
                             else {'direct':'자사몰','kakao':'카카오'}.get(r.get('platform'), r.get('platform') or '미분류')
                             for r in rows)
        return {'count':len(rows) if available else None, 'rated_count':len(values),
                'unrated_count':len(rows)-len(values),
                'average':round(sum(values)/len(values),2) if values else None,
                'low_count':low if available else None,
                'low_percent':round(low/len(values)*100,1) if values else None,
                'scores':[{'score':v,'count':n} for v,n in sorted(Counter(values).items(),reverse=True)],
                'platforms':[{'name':name,'count':n} for name,n in sorted(platforms.items())]}
    brands = [b for b in report['brands'] if b['key'] in ('jasaol','myeongga')]
    from review_types import type_statistics
    return {'types':type_statistics(report),'basis':'해당 기간에 수집된 전체 후기 기준 · 평균과 3점 이하 비율은 유효 별점 후기 기준',
            'total':aggregate([r for b in brands for r in b['reviews']], any(b.get('available',True) for b in brands)),
            'brands':[dict(key=b['key'],name=b['name'],**aggregate(b['reviews'], b.get('available',True))) for b in brands]}
