"""Copy-ready, source-phrase-based digest. No network or remote AI calls.

This is deliberately independent from the daily archive's selected excerpts and
the 500-row dashboard preview. Metrics use every applicable stored source row.
"""
from collections import Counter
from datetime import datetime
import re

from analyzer import filter_reviews, validate_range
from daily_report import KST, score
from review_summary_phrases import classify_summary_text, clean_summary_text


BRANDS = [('jasaol', '백년화편 (자사몰)'), ('myeongga', '명가삼대떡집')]
NOTICE = ('현재 저장된 전체 기간 원문 기준 · 문구 규칙으로 만든 수정 가능한 초안입니다. '
          'AI API를 호출하지 않으며, 문맥 오분류·누락 가능성이 있어 공유 전 확인해 주세요. '
          '과거 보관 보고서를 수정하지 않습니다.')
COPY_NOTE = ('※ 수집된 후기 기준이며, 한 후기가 여러 주제에 중복 집계될 수 있습니다. '
             '긍정·확인 포인트는 원문 문구 기반 요약으로 누락·오분류가 있을 수 있습니다. '
             '불만·품질 관련 내용은 고객의 표현이며 사실 확인 전 주장입니다.')


def short_date(day):
    return f'{int(day[5:7])}/{int(day[8:10])}'


def period_title(date_from, date_to):
    if date_from == date_to:
        period = short_date(date_from)
    elif date_from[:4] == date_to[:4]:
        period = f'{short_date(date_from)}~{short_date(date_to)}'
    else:
        period = f'{date_from}~{date_to}'
    return f'[{period} 후기 요약]'


def scoped_rows(source, brand, date_from, date_to):
    """Deduplicate only real source IDs; anonymous identical reviews can differ.

    jasaol's naver/kakao values represent payment providers on the direct shop.
    _load_reviews_cached explicitly marks imported Smartstore rows 'smartstore'.
    """
    rows, seen = [], set()
    for row in filter_reviews(source, date_from, date_to):
        platform = str(row.get('platform') or 'direct')
        if brand == 'jasaol' and platform not in ('direct', 'naver', 'kakao'):
            continue
        identity = None
        for field in ('review_no', 'review_id', 'id'):
            if row.get(field) not in (None, ''):
                identity = (platform, field, str(row[field]))
                break
        if identity is not None:
            if identity in seen:
                continue
            seen.add(identity)
        rows.append(row)
    return rows


def _representatives(candidates, limit=8):
    """Show diverse concerns before repeats, prioritizing material allegations.

    Ratings break ties, but never create the concern or its theme.
    """
    ranked = sorted(candidates, key=lambda r: (
        -r['severity'], r['score'] if r['score'] is not None else 6,
        r['date'], r['_index']))
    chosen, seen_themes, seen_rows = [], set(), set()
    # Broad themes must not hide materially different claims (e.g. hair,
    # rotten filling and odor) behind one generic hygiene/quality excerpt.
    material_patterns = (r'머리카락|벌레|이물질', r'곰팡이|썩|상했|상한|쉬었',
                         r'냄새|쉰내|꾸린내|군내')
    for pattern in material_patterns:
        row = next((r for r in ranked if r['severity'] >= 3
                    and r['_index'] not in seen_rows and re.search(pattern, r['excerpt'])), None)
        if row is not None and len(chosen) < limit:
            chosen.append(row)
            seen_themes.add(row['theme'])
            seen_rows.add(row['_index'])
    for row in ranked:
        if len(chosen) == limit:
            break
        if row['theme'] not in seen_themes and row['_index'] not in seen_rows:
            chosen.append(row)
            seen_themes.add(row['theme'])
            seen_rows.add(row['_index'])
            if len(chosen) == limit:
                break
    for row in ranked:
        if len(chosen) == limit:
            break
        if row['_index'] not in seen_rows:
            chosen.append(row)
            seen_rows.add(row['_index'])
    # A high rating must not bury a material issue when the digest is long.
    if chosen and not any((r['score'] or 0) >= 4 for r in chosen):
        high = next((r for r in ranked if (r['score'] or 0) >= 4
                     and r['_index'] not in seen_rows), None)
        if high is not None:
            if len(chosen) < limit:
                chosen.append(high)
            elif chosen[-1]['severity'] < 3:
                chosen[-1] = high
    return [{k: v for k, v in row.items() if k != '_index'} for row in chosen]


def brand_summary(key, name, rows, available=True):
    values = [score(row) for row in rows if score(row) is not None]
    low = sum(value <= 3 for value in values)
    positives, positive_examples = Counter(), {}
    concern_topics, candidates, concern_rows = Counter(), [], 0
    positive_low, unmatched_low = [], []
    for index, row in enumerate(rows):
        text = str(row.get('content') or '')
        result = classify_summary_text(text)
        # The classifier produces at most one evidence item per theme/review.
        for hit in result['positive']:
            positives[hit['label']] += 1
            positive_examples.setdefault(hit['label'], hit['excerpt'])
        base = {'date': row['date'], 'score': score(row), '_index': index}
        if result['concerns']:
            concern_rows += 1
        for hit in result['concerns']:
            concern_topics[hit['theme']] += 1
            candidates.append(dict(base, **hit))
        if score(row) is not None and score(row) <= 3 and not result['concerns']:
            target = positive_low if result['positive'] else unmatched_low
            target.append(dict(base, excerpt=(result['positive'][0]['excerpt']
                                             if result['positive'] else clean_summary_text(text)[:220])))
    themes = [{'label': label, 'count': count, 'example': positive_examples[label]}
              for label, count in positives.most_common(4)]
    concerns = _representatives(candidates)
    summary = {
        'key': key, 'name': name, 'available': available, 'count': len(rows),
        'rated_count': len(values), 'excluded_count': len(rows) - len(values),
        'average': round(sum(values) / len(values), 2) if values else None,
        'low_count': low,
        'low_percent': round(low / len(values) * 100, 2) if values else None,
        'positive_themes': themes, 'concerns': concerns,
        'concern_count': concern_rows,
        'concern_topics': [{'theme': theme, 'count': count}
                           for theme, count in concern_topics.most_common()],
        'positive_low_count': len(positive_low), 'unmatched_low_count': len(unmatched_low),
    }
    average = f"{summary['average']:.2f}점" if values else '산출 불가'
    percent = f"{summary['low_percent']:.2f}%" if values else '산출 불가'
    lines = [f'■ {name}', f'총 {len(rows):,}건 / 평균 {average}',
             f'3점 이하 {low:,}건 ({percent})']
    if not rows:
        lines.append('선택 기간에 저장된 후기가 없습니다. 미수집·수집 지연 여부를 확인해 주세요.')
    else:
        lines.append('긍정: ' + (' · '.join(f"{h['label']} ({h['count']:,}건)" for h in themes)
                                 if themes else '문구 규칙으로 확인된 긍정 표현 없음'))
        if concern_rows:
            lines.append('확인 포인트: ' + ' · '.join(
                f'{theme} ({count:,}건)' for theme, count in concern_topics.most_common(6)))
            if concern_rows > len(concerns):
                lines.append(f'관련 표현 {concern_rows:,}건 중 대표 {len(concerns)}건 (평점 무관)')
            for concern in concerns:
                rating = f"{concern['score']:g}점" if concern['score'] is not None else '별점 미제공'
                lines.append(f"• {short_date(concern['date'])} [{rating}] {concern['theme']}: “{concern['excerpt']}”")
        else:
            lines.append('확인 포인트: 문구 규칙으로 확인된 불만·개선 표현 없음 (누락 가능)')
        if positive_low:
            lines.append(f'별점·본문 확인: 3점 이하 중 긍정 표현이 있고 불만 문구가 확인되지 않은 후기 {len(positive_low):,}건')
            for row in positive_low[:2]:
                lines.append(f"• {short_date(row['date'])} [{row['score']:g}점] 긍정 표현: “{row['excerpt']}”")
        if unmatched_low:
            lines.append(f'추가 원문 확인: 불만 문구가 분류되지 않은 3점 이하 후기 {len(unmatched_low):,}건')
        if summary['excluded_count']:
            lines.append(f"※ 평균·3점 이하 비율은 유효 별점 {len(values):,}건 기준. 0점·별점 미제공·범위 밖 {summary['excluded_count']:,}건 제외")
        else:
            lines.append(f'※ 평균·3점 이하 비율은 유효 별점 {len(values):,}건 기준')
    summary['text'] = '\n'.join(lines)
    return summary


def build_copy_summary(cache, date_from, date_to, brand='all'):
    validate_range(date_from, date_to)
    if not date_from or not date_to:
        raise ValueError('요약할 시작일과 종료일을 선택해 주세요.')
    if brand not in ('all', 'jasaol', 'myeongga'):
        raise ValueError('지원하지 않는 브랜드입니다.')
    summaries = [brand_summary(key, name, scoped_rows(cache.get(key, []), key, date_from, date_to),
                               bool(cache.get(key)))
                 for key, name in BRANDS if brand in ('all', key)]
    title = period_title(date_from, date_to)
    text = title + '\n\n' + '\n\n'.join(item['text'] for item in summaries) + '\n\n' + COPY_NOTE
    return {'date_from': date_from, 'date_to': date_to, 'brand': brand,
            'title': title, 'text': text, 'brands': summaries,
            'total_count': sum(item['count'] for item in summaries),
            'notice': NOTICE, 'method': 'source_phrases',
            'generated_at': datetime.now(KST).isoformat(),
            'source_updated_at': cache.get('raw_last_updated')}
