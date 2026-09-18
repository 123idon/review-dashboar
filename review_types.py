"""Deterministic topic counts. Matches are mentions, not inferred sentiment."""
import re

RULES = [
 ('맛·향', r'맛|고소|담백|풍미|향긋|향이|향도|쑥향|쑥\s*향'),
 ('당도', r'달지|안\s*달|덜\s*달|많이\s*달|너무\s*달|달달|달콤|단맛|당도|설탕|안달고'),
 ('식감', r'쫄깃|쫀득|찰지|찰진|부드[러럽]|딱딱|퍽퍽|퍼석|촉촉|포슬|씹히|씹는|식감|질겨|질기'),
 ('배송·수령', r'배송|택배|배달|도착|수령|지정일|지정\s*날짜|퀵배송'),
 ('포장·보냉', r'포장|패키지|박스|아이스\s*[팩빽백]|보냉'),
 ('재료·원산지', r'국산|국내산|중국산|수입산|원산지|첨가물|재료|(?:팥|앙금|콩|밤|쑥)(?:이|도|가|은|는)?\s*(?:많|적|가득|실하|부족)'),
 ('양·크기·구성', r'크기|사이즈|구성|개수|수량|푸짐|양이|양도|양은|넉넉|든든'),
 ('가격·혜택', r'가격|가성비|저렴|비싸|비싼|할인|쿠폰|혜택|적립'),
 ('주문·상담·응대', r'상담|응대|친절|직원|전화\s*주문|주문\s*(?:오류|취소|변경)|취소|환불|교환'),
 ('선물·답례', r'선물|답례|보내드|드렸|드릴|나눠|나누어'),
 ('재구매·구매 의향', r'재구매|재주문|또\s*(?:주문|구매|구입|이용)|다시\s*(?:주문|구매|구입)|자주\s*(?:주문|구매|이용)|다음[에에도]*\s*(?:또\s*)?(?:주문|구매|구입|이용)|꾸준히|단골'),
 ('보관·해동·섭취', r'보관|냉동|해동|전자레인지|식사\s*대용|아침|간식|소화'),
 ('개선 요청', r'(?:았으면|었으면|해주시면|해주세요|해\s*주세요|늘려|줄여|낮춰|개선|다양하게\s*개발)'),
]
RULES = [(name,re.compile(pattern)) for name,pattern in RULES]
PRAISE = re.compile(r'맛있|맛나|좋아|좋네|좋습|추천|만족|최고|강추|잘\s*먹')
# General taste praise is counted separately only when no other concrete topic is mentioned.
GENERIC_TASTE = re.compile(r'맛있[가-힣]*|맛나[가-힣]*|맛난[가-힣]*')
PROBLEM = re.compile(r'딱딱[가-힣]*|퍽퍽[가-힣]*|질겨[가-힣]*|너무\s*달[가-힣]*|(?:배송|배달|택배)[^.!?\n]{0,15}?(?:늦[가-힣]*|지연[가-힣]*)|(?:포장|박스)[^.!?\n]{0,15}?(?:터졌[가-힣]*|터져[가-힣]*|파손[가-힣]*)|곰팡이|이물질')
NAMES = [name for name,_ in RULES]+['구체적 불만 표현','일반 칭찬·만족','기타·미분류','본문 없음']

def classify(text):
    text = str(text or '').strip()
    if not text: return {'본문 없음': ''}
    hits={}
    for name,pattern in RULES:
        subject = GENERIC_TASTE.sub('',text) if name=='맛·향' else text
        match=pattern.search(subject)
        if match: hits[name]=match.group()
    for m in PROBLEM.finditer(text):
        phrase=m.group()
        if re.search(r'지\s*않|진\s*않',phrase+text[m.end():m.end()+6]) or re.search(r'안\s*$',text[max(0,m.start()-3):m.start()]):
            continue
        hits['구체적 불만 표현']=phrase
        break
    if not hits:
        m=PRAISE.search(text)
        hits['일반 칭찬·만족' if m else '기타·미분류']=m.group() if m else ''
    return hits

def type_statistics(report):
    brands=[b for b in report['brands'] if b['key'] in ('jasaol','myeongga')]
    counts={name:{b['key']:0 for b in brands} for name in NAMES}
    examples={name:[] for name in NAMES}
    total=sum(len(b['reviews']) for b in brands)
    for b in brands:
        for review in b['reviews']:
            text=review.get('excerpt') or ''
            for name,phrase in classify(text).items():
                counts[name][b['key']]+=1
                if len(examples[name])<3:
                    examples[name].append({'brand':b['name'],'text':text,'phrase':phrase})
    rows=[]
    for name in NAMES:
        n=sum(counts[name].values())
        rows.append({'name':name,'count':n,'percent':round(n/total*100,1) if total else None,
                     'brands':{b['key']:counts[name][b['key']] if b.get('available',True) else None for b in brands},
                     'examples':examples[name]})
    rows.sort(key=lambda row:-row['count'])
    return {'total':total,'brands':[{'key':b['key'],'name':b['name']} for b in brands], 'rows':rows,
            'note':'수집된 전체 후기 본문 기준 · 같은 유형은 후기당 1건, 여러 유형은 중복 집계 · 비율의 분모는 전체 수집 후기 · 유형 합계와 비율 합계는 전체 건수·100%를 초과할 수 있습니다. 문구 규칙에 따른 언급 분류이며 긍정·부정이나 원인을 추정하지 않습니다. 불만 표현도 부정어·인용 문맥에 따라 오분류·누락될 수 있습니다.'}
