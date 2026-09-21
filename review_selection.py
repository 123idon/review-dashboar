"""Local, conservative evidence spans. Offsets are Unicode code points, not bytes.

Rules describe an attribute and its observed property, never a rating or product
name alone. Keep stored snapshots intact; project the current display on read.
"""
import re

VERSION = 4
# Bound gaps to the same clause; never cross punctuation/newlines.
GAP = r'[^.!?。\n,;]{0,24}?'
TAIL = r'[가-힣]*'

RULES = [
    # Sweetness praise is excluded too; retain explicit requests to reduce it.
    ('당도 개선', r'(?:조금\s*더\s*|좀\s*더\s*)?덜\s*달(?:았으면|면|아도)\s*(?:좋|했으면)' + TAIL),
    ('당도 개선', r'(?:당도|단맛|설탕)(?:를|을|이|가)?\s*(?:좀\s*|조금\s*)?(?:줄여\s*주|낮춰\s*주|줄였으면|낮췄으면)' + TAIL),
    ('맛·식감 불만', r'(?:너무|지나치게)\s*(?:달아|달고|달다|달았|짜|시어|셔서)' + TAIL),
    ('맛·식감 불만', r'(?:퍽퍽|퍼석|딱딱|질기|질겨|질겼|텁텁|푸석|눅눅|떫|느끼)' + TAIL),
    ('맛·식감 부족', r'(?:쫄깃|쫀득|고소|촉촉|부드럽|부드러|담백)' + r'[가-힣]{0,8}\s*(?:않|못|없)' + TAIL),
    ('맛·식감 부족', r'(?:쫄깃함|쫀득함|고소함|쑥\s*향|풍미)(?:이|가|은|는|도)?\s*(?:없|부족|약하|약해|덜하)' + TAIL),
    ('맛·식감 불만', r'(?:쓴맛|신맛|잡내|군내|비린맛)(?:이|가|도)?\s*(?:나|났|강하|심하)' + TAIL),
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
# Positive taste/texture/aroma alone never qualifies. Other operational rules
# remain independent, so a mixed review retains only its qualifying evidence.
RULES = [(reason, re.compile(pattern)) for reason, pattern in RULES]

# Complaints do not need a detailed operational reason. Ratings are handled
# separately so a low score never invents a negative phrase in positive text.
COMPLAINTS = [re.compile(p) for p in [
    r'(?:실망|불만족|불만|불편|불친절|불쾌|아쉽|아쉬|속상|섭섭|최악|별로|비추|후회|짜증|화가\s*나|화나|황당|어이없)[가-힣]*',
    r'(?:맛\s*없|맛\s*이\s*없|맛이\s*이상|맛이\s*변했|맛이\s*달라|맛없|비싸|비싼|비쌉|비쌌|아깝|아까워|부실|불량|파손|누락|오배송|변질|상했|쉰내)[가-힣]*',
    r'(?:마음에|맘에)\s*안\s*들[가-힣]*|(?:좋지|괜찮지|만족스럽지)\s*않[가-힣]*',
    r'(?:다시는|다신)\s*(?:안|못)\s*(?:사|살|먹|주문|구매)[가-힣]*|(?:재구매|재주문)\s*(?:안|없|못)[가-힣]*',
    r'(?:환불|반품|교환)(?:을|를)?\s*(?:요청|원해|해\s*주|해주세요|부탁|했|합|할|받|신청)[가-힣]*',
    r'(?:주문|예약|결제|연락|통화|배송|해동|분리|씹기|먹기)[^.!?。\n,;]{0,18}?(?:안\s*되|안돼|안\s*돼|못\s*하|못해|어렵|어려|힘들|불가)[가-힣]*',
    r'(?:크기|사이즈|양|수량|개수|갯수|구성)[^.!?。\n,;]{0,18}?(?:줄었|줄고|줄어|줄어서|작아졌|작아|적어|적었|부족)[가-힣]*',
    r'(?:배송|도착|답변|응답)[^.!?。\n,;]{0,18}?(?:느리|느려|늦|지연|안\s*왔|없)[가-힣]*',
    r'(?:떡|제품|상품|포장|박스)[^.!?。\n,;]{0,18}?(?:깨져|깨졌|터져|터졌|찢어|새어|새고|잘못|빠졌|빠져)[가-힣]*',
]]
COMPLAINT_NEGATION = re.compile(r'(?:지|진)\s*않|(?:은|는|이|가)?\s*없|아니')

def complaint_highlights(text):
    hits = []
    for pattern in COMPLAINTS:
        for match in pattern.finditer(text):
            # Suppress "불만 없어요", "비싸지 않아요", "별로 안 달아요".
            if COMPLAINT_NEGATION.match(text[match.end():].lstrip()):
                continue
            phrase = match.group()
            if re.search(r'(?:지|진)\s*않|(?:불만|불편|아쉬움)(?:이|은|는)?없', phrase + text[match.end():match.end()+8]):
                continue
            if phrase.startswith('별로') and re.match(r'\s*(?:안|없|않)',text[match.end():]):
                continue
            hits.append({'start':match.start(),'end':match.end(),'kind':'reason','reason':'고객 불만'})
    return hits

def low_rating(value):
    try:
        return 1 <= float(value) <= 3
    except (ValueError, TypeError):
        return False

PROBLEM_NEGATION = re.compile(
    r'(?:딱딱|질기|질겨|퍽퍽|퍼석|푸석|텁텁|느끼|눅눅|떫|달|짜|굳|상하|상해|붙|녹)'
    r'[가-힣]{0,3}(?:지\s*않|진\s*않)|'
    r'(?:쓴맛|신맛|잡내|군내|비린맛|냄새)(?:이|가|도)?\s*(?:나지\s*않|없)')


def highlights(text):
    hits = complaint_highlights(text)
    for reason, pattern in RULES:
        for match in pattern.finditer(text):
            phrase = match.group()
            # Include local negation in the evidence instead of coloring a lone word.
            end = match.end()
            glued = re.search(r'(?:너무|넘맛|정말|맛있)', phrase)
            if glued and glued.start() > 0 and not phrase[glued.start()-1].isspace():
                end = match.start() + glued.start()
            suffix = re.match(r'\s*(?:않[가-힣]*|안\s*[가-힣]+|못[가-힣]*)', text[end:])
            if suffix:
                end += suffix.end()
            # "딱딱하지 않다 / 안 질기다 / 굳지 않는다" is positive,
            # not a complaint. Apply this only to inherently negative predicates.
            if reason in {'맛·식감 불만', '품질 문제', '분리·해동', '분리', '냄새'}:
                evidence = text[match.start():end]
                if PROBLEM_NEGATION.search(evidence) or re.search(r'안\s*$', text[max(0, match.start()-3):match.start()]):
                    continue
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
            if spans or low_rating(review.get('score')):
                reviews.append(dict(review, highlights=spans))
        reviews.sort(key=lambda r: len(r['excerpt']), reverse=True)
        brands.append(dict(brand, reviews=reviews, selected_count=len(reviews)))
    result.update(brands=brands, selected_count=sum(b['selected_count'] for b in brands),
                  selection_version=VERSION,
                  selection_rule='3점 이하 후기 전부 포함 · 평점과 관계없이 부정·고객 불만 표현 포함 · 본문 전체 · 글자 수 많은 순',
                  highlight_rule='불만은 짧아도 포함 · 실제 평가 문구만 강조 · 단순 당도·맛·식감·향 칭찬 제외 · 기존 구체적 이유 선정 유지')
    return result
