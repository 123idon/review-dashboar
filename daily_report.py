"""Deterministic daily review digest; no LLM, network, or message sending."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
import re

KST = ZoneInfo('Asia/Seoul')
BRANDS = [('jasaol', '백년화편', '자사'), ('myeongga', '명가삼대떡집', '경쟁사'),
          ('papa', '파파공방', '경쟁사'), ('changeok', '창억떡', '경쟁사')]
NEGATIVE = ('곰팡이', '이물질', '상했', '불량', '파손', '누락', '오배송', '배송 지연',
            '딱딱', '질기', '맛없', '실망', '불친절', '환불', '아쉽', '너무 달', '녹아서')
POSITIVE = ('재구매', '재주문', '맛있', '쫄깃', '부드럽', '만족', '추천', '친절', '빠른 배송', '선물')


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


def excerpt(text, limit=180):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(text) <= limit:
        return text
    positions = [text.find(k) for k in NEGATIVE if k in text]
    start = max(0, min(positions)-30) if positions else 0
    return ('…' if start else '') + text[start:start+limit] + ('…' if start+limit < len(text) else '')


def highlights(text):
    pattern = '|'.join(re.escape(k) for k in sorted(NEGATIVE + POSITIVE, key=len, reverse=True))
    return [{'start': m.start(), 'end': m.end(), 'kind': 'negative' if m.group() in NEGATIVE else 'positive'}
            for m in re.finditer(pattern, text)]


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
        unavailable = key == 'changeok' and not source
        values = [score(r) for r in rows if score(r) is not None]
        low = [r for r in rows if score(r) is not None and score(r) <= 3]
        def rank(r):
            text = str(r.get('content', ''))
            return (0 if score(r) is not None and score(r) <= 3 else 1,
                    -sum(k in text for k in NEGATIVE), score(r) or 6,
                    -sum(k in text for k in POSITIVE), -len(text))
        useful = [r for r in rows if str(r.get('content', '')).strip()]
        picked = sorted(useful, key=rank)[:2]
        positive = sorted([r for r in useful if score(r) is not None and score(r) >= 4 and r not in picked],
                          key=lambda r: (-sum(k in str(r.get('content', '')) for k in POSITIVE), -len(str(r.get('content', '')))))
        if positive:
            picked.append(positive[0])
        else:
            picked += [r for r in sorted(useful, key=rank) if r not in picked][:3-len(picked)]
        selected = []
        for row in picked:
            text = excerpt(row.get('content'))
            selected.append({'score': score(row), 'product': str(row.get('product') or '상품명 미제공')[:65],
                             'platform': str(row.get('platform') or '미분류'), 'excerpt': text,
                             'highlights': highlights(text)})
        if unavailable:
            coverage = '수집 미구현 · 비교 집계 제외'
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
    return {'date': target, 'generated_at': clock.astimezone(KST).isoformat(), 'timezone':'Asia/Seoul',
            'total':total, 'low_count':sum(c['low_count'] or 0 for c in cards), 'brands':cards,
            'notice':'수집된 후기만 집계합니다. 미수집·지연 채널은 전체 수치에서 누락될 수 있습니다.',
            'selection_rule':'브랜드별 최대 3건 · 저평점/불만 키워드 우선, 칭찬 후기 보완 · 원문 일부 발췌',
            'highlight_rule':'분홍: 불만 관련 단어 / 노랑: 칭찬·재구매 관련 단어. 단어 표시이며 문맥 판단은 필요합니다.'}


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
