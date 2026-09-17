"""Local, conservative evidence spans. Offsets are Unicode code points, not bytes.

Rules describe an attribute and its observed property, never a rating or product
name alone. Keep stored snapshots intact; project the current display on read.
"""
import re

VERSION = 1
# Bound gaps to the same clause; never cross punctuation/newlines.
GAP = r'[^.!?。\n,;]{0,24}?'
TAIL = r'[가-힣]*'

RULES = [
    ('당도', r'(?:많이\s*|너무\s*|넘\s*)?(?:달지(?:도)?\s*않|안\s*달|덜\s*달|적당히\s*달|달지도\s*싱겁지도\s*않)' + TAIL),
    ('당도', r'(?:너무|많이|좀\s*더)\s*(?:달아|달고|달다|달았|단맛)' + TAIL),
    ('당도', r'(?:팥소|앙금|팥|소)(?:가|는|도)?\s*저당' + TAIL),
    ('식감', r'(?:쫀득|쫄깃|쫀쫀|말랑|촉촉|부드럽|부드러|고소|담백|퍽퍽|퍼석|딱딱|질기|질겨|질겼|쫀든|촐깃)' + TAIL),
    ('밥알 식감', r'밥알(?:이|도|\s*하나씩)?\s*(?:살아\s*있|씹)' + TAIL),
    ('향·맛', r'(?:쑥\s*향|향|맛)(?:이|도|은|가)?\s*(?:너무\s*|정말\s*|아주\s*)?(?:진하|진해|진한|좋|은은|향긋|깔끔)' + TAIL),
    ('향·맛', r'(?:진한|진하게|은은한|향긋한)\s*쑥\s*향' + TAIL),
    ('재료·양', r'(?:팥|앙금|팥소|쑥양|쑥|콩|밤|밤고|견과류)(?:이|가|도|은|는)?' + GAP + r'(?:많아|많이\s*들|많아서|가득|넉넉|실하|실하고|적어|부족)' + TAIL),
    ('크기·구성', r'(?:크기|사이즈|개수|구성|건강떡)(?:가|이|도|는)?' + GAP + r'(?:크고|커서|작아|작아서|적당|많지\s*않|좀\s*더\s*있었으면)' + TAIL),
    ('포장', r'(?:포장|박스|패키지)' + GAP + r'(?:고급|견고|위생적|꼼꼼|예쁘|예뻐|뜯기\s*어려|터져|터졌|찢어|찢었|파손|새서)' + TAIL),
    ('포장', r'(?:개별|낱개)\s*포장' + GAP + r'(?:편리|편하|편해|좋|위생)' + TAIL),
    ('보냉', r'아이스\s*(?:팩|빽|백)' + GAP + r'(?:없이|없어|없었|녹아)' + TAIL),
    ('배송 문제', r'(?:배송|배달|도착|지정\s*날짜|지정일|날짜)(?!\s*지정)'  + GAP + r'(?:늦|지연|미뤄|다음날)' + TAIL),
    ('품질 문제', r'(?:떡|가운데|중간|제품)(?:이|가|은|는)?' + GAP + r'(?:굳어|상했|쉬었|녹아|붙어)' + TAIL),
    ('품질 문제', r'(?:곰팡이|이물질|머리카락|벌레)' + GAP + r'(?:나왔|나와|있었|있어|발견|들어)' + TAIL),
    ('분리·해동', r'(?:해동|분리)' + GAP + r'(?:안\s*되|안돼|어려|힘들|딱딱)' + TAIL),
    ('주문·상담', r'(?:전화\s*주문|상담|응대)' + GAP + r'(?:편리|친절|불친절|불편|할\s*수가\s*없)' + TAIL),
    ('소화', r'소화(?:가|도)?\s*(?:진짜\s*|너무\s*)?(?:잘\s*되|잘\s*돼|안\s*되|잘\s*안\s*되)' + TAIL),
    ('당도', r'적당한\s*당도|달짝지근[가-힣]*'),
    ('재료', r'(?<!중)(?:국산|국내산)\s*(?:재료|식재료)|첨가물\s*(?:없이|없고|없어)'),
    ('원산지', r'(?:흑임자|팥|쑥|콩|재료)(?:가|이|는|도)?\s*(?:중국산|수입산)' + GAP + r'(?:그렇지만|아쉽|불만|걱정)[가-힣]*'),
    ('배송 문제', r'(?:택배|배송|배달)' + GAP + r'(?:지연|늦|오지\s*않|안\s*왔)[가-힣]*'),
    ('포장', r'포장이\s*품격[가-힣]*|개별\s*포장[^.!?。\n]{0,65}?고급[가-힣]*'),
    ('상담', r'친절[가-힣]*' + GAP + r'(?:상담|응대|가르쳐\s*주)[가-힣]*'),
    ('매장·응대', r'(?:직원분들|직원|매장)' + GAP + r'(?:친절|청결|깔끔)[가-힣]*'),
    ('분리', r'(?:서로\s*붙|눌러붙|분리하기\s*어렵|분리하기\s*어려)[가-힣]*(?:\s*않[가-힣]*)?'),
    ('품질·수량', r'(?:포장|제품|상품|떡|수량)' + GAP + r'(?:누락|빠져|빠졌|잘못\s*왔|부족)[가-힣]*'),
    ('냄새', r'(?:쉰|상한|이상한)\s*냄새|냄새(?:가|도)?\s*(?:심하|심해|나서|났)[가-힣]*'),
]
# Generic "맛이 좋아요" is deliberately not a sensory explanation.
RULES = [(reason, re.compile(pattern)) for reason, pattern in RULES]


def highlights(text):
    hits = []
    for reason, pattern in RULES:
        for match in pattern.finditer(text):
            phrase = match.group()
            if reason == '향·맛' and re.fullmatch(r'맛(?:이|도|은|가)?\s*(?:너무\s*|정말\s*|아주\s*)?좋[가-힣]*', phrase):
                continue
            # Include local negation in the evidence instead of coloring a lone word.
            end = match.end()
            glued = re.search(r'(?:너무|넘맛|정말|맛있)', phrase)
            if glued and glued.start() > 0 and not phrase[glued.start()-1].isspace():
                end = match.start() + glued.start()
            suffix = re.match(r'\s*(?:않[가-힣]*|안\s*[가-힣]+|못[가-힣]*)', text[end:])
            if suffix:
                end += suffix.end()
            hits.append({'start': match.start(), 'end': end, 'kind': 'reason', 'reason': reason})
    hits.sort(key=lambda h: (h['start'], -h['end']))
    result = []
    for hit in hits:
        if result and hit['start'] < result[-1]['end']:
            result[-1]['end'] = max(result[-1]['end'], hit['end'])
        else:
            result.append(hit)
    return result


def select_report(report):
    """Non-mutating view of full schema-2 snapshots, also used for old dates."""
    result = dict(report)
    brands = []
    for brand in report['brands']:
        if brand['key'] not in ('jasaol', 'myeongga'):
            continue
        reviews = []
        for review in brand['reviews']:
            spans = highlights(review.get('excerpt') or '')
            if spans:
                reviews.append(dict(review, highlights=spans))
        reviews.sort(key=lambda r: len(r['excerpt']), reverse=True)
        brands.append(dict(brand, reviews=reviews, selected_count=len(reviews)))
    result.update(brands=brands, selected_count=sum(b['selected_count'] for b in brands),
                  selection_version=VERSION,
                  selection_rule='구체적인 평가 이유가 있는 후기 선정 · 본문 생략 없음 · 글자 수 많은 순',
                  highlight_rule='당도·식감·향·재료·포장·배송 등 평가 이유를 설명하는 원문 구절 강조')
    return result
