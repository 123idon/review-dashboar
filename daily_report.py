"""Deterministic daily review digest; no LLM, network, or message sending."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
import re

KST = ZoneInfo('Asia/Seoul')
BRANDS = [('jasaol', '백년화편', '자사'), ('myeongga', '명가삼대떡집', '경쟁사')]
# Concrete operational signals only. Generic praise and purchase intent are excluded.
ISSUE_RULES = [
    ('품질·위생', r'곰팡이|이물질|머리카락|벌레|상한\s*냄새|쉰\s*냄새|(?:떡|제품|상품|음식)(?:이|은|가|는)?\s*상했|(?:^|\s)상했|변질'),
    ('배송·포장', r'오배송|누락|파손|터져|터졌|찢어|찢어졌|새서|샜|녹아서|녹아\s*왔|배송.{0,12}(?:늦|지연)|(?:다른|잘못된)\s*상품'),
    ('식감·맛', r'너무\s*(?:달|짜|딱딱|질겨)|딱딱해서|딱딱해져|질겨서|퍽퍽해서|냄새가\s*(?:심|나)|(?:예전|지난번|전보다).{0,18}(?:달라|줄었|작아|딱딱|덜|떨어)'),
    ('개선 요청', r'(?:포장|배송|크기|양|당도|식감|가격|보관|해동).{0,35}(?:개선|바꿔|줄여|늘려|해\s*주(?:세요|셨으면|시면)|해주면|했으면|하면\s*좋|아쉽)'),
]
NEGATION = re.compile(r'(?:곰팡이|이물질|머리카락|벌레|파손|누락|오배송).{0,10}(?:없|아니)|(?:딱딱|질기|질겨|달지|짜지).{0,8}(?:않|안)|배송.{0,10}늦지\s*않')


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


def highlights(text):
    """Highlight at most two actionable clauses, with reasons; no sentiment claims."""
    result = []
    for match in re.finditer(r'[^.!?。\n,;]+', text):
        raw = match.group()
        phrase = raw.strip()
        if not phrase or NEGATION.search(phrase):
            continue
        for reason, pattern in ISSUE_RULES:
            hit = re.search(pattern, phrase)
            if not hit:
                continue
            # Cap a very long run-on clause around its concrete issue.
            left = max(0, hit.start()-35)
            right = min(len(phrase), max(hit.end()+55, left+75))
            offset = match.start()+len(raw)-len(raw.lstrip())
            result.append({'start':offset+left,'end':offset+right,'kind':'negative','reason':reason})
            break
        if len(result) == 2:
            break
    return result


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
            ident = (row.get('author', ''), row.get('date', ''), str(row.get('content', ''))[:100])
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
                             'highlights': highlights(text), 'date':target})
        # All rows are retained; actionable issues and low ratings appear first.
        selected.sort(key=lambda r: (not bool(r['highlights']), r['score'] if r['score'] is not None else 6))
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
            'selection_rule':'백년화편·명가삼대떡집의 저장된 전일 후기 전체 · 본문 생략 없음 · 확인할 내용 우선',
            'highlight_rule':'형광펜: 품질·위생, 배송·포장 사고, 구체적인 불만·개선 요청 문장만 표시. 일반 칭찬은 제외하며 규칙 기반이므로 문맥 확인이 필요합니다.'}


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
