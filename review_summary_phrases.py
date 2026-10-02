"""Conservative, local evidence rules for the copyable review summary.

These are observed phrases, not sentiment scores or verified product facts.
A review can provide both positive and concern evidence, regardless of its stars.
Excerpts preserve source wording except for explicit private-detail redaction. Product names,
ratings, topic-count rules and remote inference are deliberately not used here.
"""
import re

# Keep rules inside a sentence; a distant adjective must not qualify a topic.
GAP = r'[^.!?。;\n]{0,30}?'
SHORT = r'[^.!?。;\n]{0,15}?'
FOOTER = re.compile(r'\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*에\s*등록된\s*네이버\s*페이\s*구매평\)')
SENTENCE = re.compile(r'[^.!?。;\n]+[.!?。;]*')

# Label, pattern, optional contextual guard. Labels are intentionally modest:
# "만족" and "언급" describe customer wording, never a product guarantee.
POSITIVE_RULES = [
    ('쫀득·부드러운 식감', r'쫄깃|쫀득|쫀듯|쫀딕|쫀쫀|말랑|부드럽|부드러|촉촉|찰지|찰진', 'ordinary'),
    ('과하지 않은 단맛', r'(?:많이\s*|너무\s*)?달(?:지|진|지는|지도)\s*않|안\s*달|덜\s*달|적당(?:히|한)\s*(?:달|단맛|당도)', 'sweetness'),
    ('맛·향 만족', r'맛\s*있|맛나|맛난|맛(?:이|도|은)?\s*좋|고소|담백|(?:쑥\s*향|향긋|풍미|향기)(?:이|가|도|은)?' + SHORT + r'(?:좋|진하|진해|살아)', 'ordinary'),
    ('풍성한 재료·속', r'(?:팥|앙금|팥소|쑥|밤|견과류|견과|호두|콩|초코|재료)(?:이|가|도|은|는)?' + SHORT + r'(?:많|가득|듬뿍|넉넉|푸짐|실하|실합)', 'ordinary'),
    ('양·크기 만족', r'(?:크기|사이즈|양|구성)(?:가|이|도|는|은)?' + SHORT + r'(?:적당|넉넉|푸짐|만족)|(?:떡|속)(?:이|가|도)?\s*(?:정말\s*|너무\s*)?실하', 'ordinary'),
    ('포장 만족·개별포장 편의', r'(?:포장|박스|패키지)' + SHORT + r'(?:꼼꼼|깔끔|고급|예쁘|예뻐|정성|좋)|(?:개별|낱개)\s*포장' + GAP + r'(?:편리|편하|편해|좋|맘에\s*듭|마음에\s*듭)|정성\s*가득\s*포장', 'ordinary'),
    ('간편한 식사·간식', r'(?:식사\s*대용|아침|간식)' + GAP + r'(?:간편|편리|좋|든든|포만)|(?:간편|편리)' + SHORT + r'(?:식사\s*대용|아침|간식)', 'ordinary'),
    ('선물·받는 분 만족', r'선물' + GAP + r'(?:좋아|좋았|좋습|좋은|딱|만족|감사|맛있|든든)|(?:받으시는\s*분|받는\s*분|받으신\s*분|받으신분)' + SHORT + r'(?:좋아|만족)|선물\s*할\s*때마다\s*좋은\s*인사', 'ordinary'),
    ('재구매·반복 이용', r'재구매|재주문|(?:또|다시|계속|꾸준히|자주|매번|늘)\s*(?:주문|구매|구입|먹)|(?:다음에도|다음에|다음\s*명절에도)' + SHORT + r'(?:주문|구매|부탁)', 'repurchase'),
    ('빠른 배송·친절한 응대', r'(?:배송|택배|배달|도착)' + SHORT + r'(?:빠르|빨라|빨리|빠르게|신속)|빠른\s*(?:배송|배달)|(?<!불)친절', 'ordinary'),
]

# Severity is priority for the digest, not a judgment that the allegation is true.
CONCERN_RULES = [
    ('이물·위생 관련 언급', r'(?:머리카락|벌레|곰팡이|이물질)' + SHORT + r'(?:나왔|나와|있었|있어|발견|들어|섞|보였)|비위생|위생' + SHORT + r'(?:신경\s*쓰|신경을\s*쓰|걱정|불안)', 3, 'ordinary'),
    ('변질·이취 관련 언급', r'썩었|썩은|썩어|(?<![예상])상했|(?<![이상])상한|(?:떡|제품|음식|밤)(?:이|가|도)?' + SHORT + r'쉬었|쉰내|꾸린내|군내|(?:쉰|상한|이상한|오래된)\s*냄새|냄새(?:가|도)?\s*(?:심하|심해)|이\s*냄새의\s*정체', 3, 'ordinary'),
    ('보냉·해동 상태', r'(?:아이스\s*[팩빽백]|얼음\s*팩)' + SHORT + r'(?:없|없이|빠져|빠졌|녹|터져|터졌)|녹(?:아|았|고|은)' + SHORT + r'(?:왔|왓|와서|온|오긴|오다|도착|배송)|(?:받아\s*보니|받았는데|도착했는데)' + SHORT + r'녹', 2, 'ordinary'),
    ('포장 파손·내용물 누출', r'(?:포장|박스|패키지|내용물|반죽)' + GAP + r'(?:터져|터졌|찢어|찢었|파손|샜|새어|새서|깨져|깨졌)|(?:터져|터졌|찢어|찢었|파손|샜|새어|깨져|깨졌)' + SHORT + r'(?:왔|와서|온|도착)|(?:제품|반죽|안에)' + SHORT + r'물이\s*들어', 2, 'ordinary'),
    ('배송 지연·수령 문제', r'(?:배송|택배|배달|도착|수령|지정\s*날짜|지정일)' + GAP + r'(?:늦|지연|안\s*왔|오지\s*않|미뤄)|(?:지정\s*날짜|지정일)' + SHORT + r'다음날|(?:당일배송|당일발송)' + GAP + r'[2-9]\d*일째', 2, 'ordinary'),
    ('누락·오배송', r'(?:수량|제품|상품|떡|포장|주문)' + GAP + r'(?:누락|빠져|빠졌|잘못\s*왔|잘못\s*보내|덜\s*왔)|오배송|누락', 2, 'ordinary'),
    ('해동·식감 아쉬움', r'딱딱|퍽퍽|퍼석|푸석|질겨|질기|질긴|질겼|텁텁|눅눅|느끼(?:해|하|했|함)|굳(?:어|었|은|고)|덜\s*물렁|(?:해동|분리)' + SHORT + r'(?:안\s*되|안돼|안\s*돼|어려|어렵|힘들)|(?:쫀득|쫄깃|부드럽|부드러|촉촉)(?:하지|하진|하지는|지|진|지는|함이|함은|함도)\s*(?:않|없)', 1, 'texture'),
    ('맛·당도 아쉬움', r'(?:너무|지나치게|과하게|많이)\s*(?:달|짜)|(?<![단입])맛\s*없|(?<![단입])맛이\s*없|맛이\s*이상|(?:쑥\s*향|고소함|풍미)(?:이|가|도|은)?\s*(?:없|부족|약하|약해)|(?:쓴맛|신맛|잡내|비린맛)(?:이|가|도)?\s*(?:나|강하|심하)', 1, 'ordinary'),
    ('양·크기·구성 아쉬움', r'(?:양|크기|사이즈|수량|개수|갯수|구성)(?:이|가|도|은|는)?' + SHORT + r'(?:줄었|줄고|줄어|작아|작았|적어|적었|부족)|(?:견과류|재료|밤|팥|앙금)' + SHORT + r'(?:적어|부족|많이\s*들어있지는\s*않)', 1, 'ordinary'),
    ('가격·혜택 아쉬움', r'비싸|비싼|비쌉|비쌌|가격' + SHORT + r'(?:아쉽|부담|높|손해)|할인이\s*할인이\s*아니', 1, 'ordinary'),
    ('주문·상담·응대 아쉬움', r'불친절|(?:상담|응대|연락|전화|통화|주문)' + SHORT + r'(?:불편|안\s*되|안돼|못\s*하|못해|어렵|어려(?:워|웠|운|움|요)|불가)|(?:환불|반품|교환)(?:을|를)?\s*(?:요청|원해|해\s*주|부탁|신청)', 1, 'ordinary'),
    ('개선·선택지 요청', r'(?:무당|무설탕|저염|저당|건강떡|영양찰떡)' + GAP + r'(?:만들어|개발|선택|따로)' + SHORT + r'(?:주|좋)|따로\s*해\s*주|(?:조금\s*더\s*|좀\s*더\s*)?덜\s*달(?:았으면|면|아도)\s*(?:좋|했으면)|(?:당도|단맛|설탕)' + SHORT + r'(?:줄여\s*주|낮춰\s*주|줄였으면|낮췄으면)|(?:포장|아이스\s*팩|수량|구성|종류|크기)' + GAP + r'(?:늘려|줄여|개선|신경\s*써|신경\s*쓰|꼼꼼하게\s*해)\s*주(?:세요|시면[^.!?。;\n]{0,12}좋|셨으면|시길)', 1, 'request'),
    ('기타 불만·아쉬움', r'실망|불만족|불만|불편|불쾌|아쉽|아쉬|속상|섭섭|최악|(?<![가-힣])별로|비추|후회|짜증|황당|어이없', 1, 'generic'),
]
POSITIVE_RULES = [(label, re.compile(pattern), guard) for label, pattern, guard in POSITIVE_RULES]
CONCERN_RULES = [(theme, re.compile(pattern), severity, guard) for theme, pattern, severity, guard in CONCERN_RULES]

# Read enough adjoining grammar to cover glued Korean text and nominal negation:
# "딱딱하지 않다", "퍽퍽함이 없다", "불만은 없다", "비싸진 않다".
NEGATED_AFTER = re.compile(r'^[가-힣]{0,7}\s*(?:않|없|아니)')
HYPOTHETICAL_AFTER = re.compile(
    r'^[가-힣]{0,9}\s*(?:줄\s*알|까\s*(?:봐|걱정)|수도\s*있|것\s*같|거\s*같)|'
    r'^[가-힣]{0,7}(?:할줄|할\s*줄)|'
    r'^[가-힣]{0,8}(?:기\s*마련|면\s*(?:어쩌|어떡|안\s*되))')
NEGATIVE_PRAISE_AFTER = re.compile(r'^[가-힣]{0,6}\s*(?:않|없|아니|못)|^[가-힣]{0,6}\s*별로')
NEGATIVE_PRAISE_BEFORE = re.compile(r'(?:안|못|전혀)\s*$')


EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.-])')
PHONE = re.compile(r'(?<!\d)(?:\+82[-.\s]?(?:0?1[016789]|0?[2-6]\d?)|0(?:1[016789]|2|[3-6]\d))[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)')
REGION = r'(?:서울(?:특별시|시)?|부산(?:광역시|시)?|대구(?:광역시|시)?|인천(?:광역시|시)?|광주(?:광역시|시)?|대전(?:광역시|시)?|울산(?:광역시|시)?|세종(?:특별자치시|시)?|경기(?:도)?|강원(?:특별자치도|도)?|충청[남북]도|충[남북]|전라[남북]도|전[남북]|경상[남북]도|경[남북]|제주(?:특별자치도|도)?)'
UNIT = r'(?:\s*\d{1,5}(?:동|호|층)){0,3}'
HOUSE_NUMBER = r'\d{1,5}(?:-\d{1,5})?(?![\d,]|\s*(?:원|개|점|그램|kg|g))'
ADDRESS = re.compile(r'(?:' + REGION + r'\s+(?:[가-힣0-9]+(?:시|군|구|읍|면)\s+){0,4})?[가-힣0-9]+(?:대로|로|길)\s*' + HOUSE_NUMBER + UNIT + r'|'
                     + REGION + r'\s+(?:[가-힣0-9]+(?:시|군|구|읍|면)\s+){0,4}[가-힣0-9]+동\s*' + HOUSE_NUMBER + UNIT + r'|\b\d{1,5}동\s*\d{1,5}호\b')


def redact_private_details(text):
    """Hide obvious contact details and street/unit addresses in copied text.

    This narrow safeguard does not infer names, redact prices/product names,
    or promise to recognize every form of personal information.
    """
    text = str(text or '')
    text = EMAIL.sub('[이메일 숨김]', text)
    text = PHONE.sub('[전화번호 숨김]', text)
    return ADDRESS.sub('[주소 숨김]', text)


def clean_summary_text(text):
    """Remove import-only Naver footer and redact obvious private details."""
    return redact_private_details(FOOTER.sub('', str(text or ''))).strip()


def _sentences(text):
    """Keep original spelling and whitespace, dropping only import metadata."""
    for block in FOOTER.split(text):
        for match in SENTENCE.finditer(block):
            sentence = match.group().strip()
            if sentence:
                yield sentence


def _excerpt(sentence, match, limit=220):
    """A source sentence, or a literal context window for unusually long ones."""
    if len(sentence) <= limit:
        return sentence
    start = max(0, match.start() - 65)
    end = min(len(sentence), max(match.end() + 65, start + limit))
    start = max(0, end - limit)
    # Prefer a nearby word boundary without deleting the matched evidence.
    boundary = sentence.find(' ', start, min(match.start(), start + 20))
    if boundary >= 0:
        start = boundary + 1
    return sentence[start:end].strip()


def _negated(sentence, match):
    before = sentence[max(0, match.start() - 10):match.start()]
    after = sentence[match.end():match.end() + 35].lstrip()
    embedded = re.search(r'(?:안|전혀)\s*(?:녹|늦|터|딱딱|질기|부족)[가-힣]*$', match.group()[-20:])
    coordinated = re.match(r'^[가-힣]{0,4}(?:거나|고|지도)\s*(?:달|짜|질기|딱딱)[가-힣]{0,5}\s*않', after)
    typo_negation = re.match(r'^[가-힣]{0,4}(?:지|진|지는|지도)\s*안(?:아|고|았|아요)', after)
    return bool(embedded or coordinated or typo_negation or re.search(r'(?:안|전혀)\s*$', before) or NEGATED_AFTER.match(after))


def _hypothetical(sentence, match):
    """Avoid interpreting feared/expected texture as an observed defect."""
    after = sentence[match.end():match.end() + 35]
    if HYPOTHETICAL_AFTER.match(after):
        return True
    return False


def _positive_allowed(sentence, match, guard):
    before = sentence[max(0, match.start()-12):match.start()]
    after = sentence[match.end():match.end()+40]
    if '불편' in match.group() or '불친절' in match.group():
        return False
    if re.match(r'^[가-힣]{0,6}\s*(?:느끼|부담|싫|아쉽|물리|물려)', after):
        return False
    if re.match(r'^[가-힣]{0,4}\s*(?:볼|할)\s*수\s*없', after):
        return False
    if NEGATIVE_PRAISE_BEFORE.search(before):
        return False
    if guard != 'sweetness' and NEGATIVE_PRAISE_AFTER.match(after):
        return False
    if _hypothetical(sentence, match):
        return False
    if re.match(r'^[가-힣]{0,5}\s*다고\s*(?:해서|하여|하길래|들어|들었)', after):
        return False
    if re.match(r'^[가-힣]{0,3}\s*(?:들어|들|담겨)[가-힣]{0,8}\s*(?:않|없)', after):
        return False
    if guard == 'repurchase':
        after = after.lstrip()
        if re.match(r'^(?:(?:은|는|도|를)\s*)?(?:할\s*)?(?:생각|의향)(?:이|은|도)?\s*(?:안|못|없)', after):
            return False
        if re.match(r'^(?:은|는|도)?\s*하(?:지|진|지는)\s*않', after):
            return False
        if re.match(r'^(?:는|도|를|할|하진|하지는|하지|할\s*생각|할\s*의향)?\s*(?:안|않|못|없)', after):
            return False
        if re.search(r'(?:다시|다신|다시는)\s*(?:안|못)\s*$', before):
            return False
    if guard == 'sweetness':
        if re.match(r'^[가-힣]{0,5}(?:으면|면|아도)\s*(?:좋|했으면)', after):
            return False
        # Less sweet is not automatically praise if the customer dislikes it.
        if re.match(r'^[가-힣]{0,7}\s*(?:맛\s*없|싱겁|아쉽|아쉬|별로|싫)', after):
            return False
        if re.search(r'(?:너무|전혀)\s*$', before) and not re.search(r'좋|맛있|만족|담백', sentence):
            return False
    return True


def _concern_allowed(sentence, match, guard):
    # Repeating somebody else's alleged defect is not this customer's finding.
    after = sentence[match.end():match.end()+45]
    if re.match(r'^[가-힣]{0,4}(?:다는|라는|다고)' + SHORT + r'(?:후기|리뷰|소문|말)', after):
        return False
    if re.search(r'(?:떡|떡집|제품|상품)에\s*(?:(?:푹|완전|더)\s*)?빠(?:져|졌)', match.group()):
        return False
    before = sentence[max(0, match.start()-25):match.start()]
    phrase = match.group()
    if re.search(r'인위적[가-힣]*\s*$', before) and phrase.startswith('맛'):
        return False
    if re.search(r'(?:맛이?\s*없)', phrase) and re.match(r'^[가-힣]{0,6}\s*(?:떡이?\s*없|수가?\s*없)', after):
        return False
    if re.search(r'(?:일반\s*기성품|다른\s*(?:집|떡)|그동안\s*주문)', before):
        return False
    if re.search(r'(?:이건|이\s*떡은|명가\s*떡은).*?(?:쫀득|맛있|좋|달지)', sentence[match.end():]):
        return False
    if re.search(r'(?:너무|많이)\s*달', phrase) and re.match(r'^[가-힣]{0,8}\s*(?:꼬소해서\s*)?(?:만족|맛있|좋)', after):
        return False
    if guard != 'request' and (_negated(sentence, match) or _hypothetical(sentence, match)):
        return False
    if guard == 'generic':
        # "맛있어요 사라지는게 아쉬울뿐" regrets finishing enjoyable food,
        # not a product problem. Keep this local to the current praise clause;
        # separate quantity, packaging, delivery and discontinuation issues stay.
        clause = re.split(r'[,，]|그런데|하지만|그러나|(?:지만|는데)',
                          sentence[:match.start()])[-1]
        if (phrase.startswith(('아쉽', '아쉬'))
                and re.search(r'맛\s*있|맛나|잘\s*먹', clause)
                and re.search(r'(?:사라지는|없어지는)\s*(?:게|것이|것만)\s*$', clause)
                and not re.search(r'포장|배송|택배|수량|양이|크기|품절|단종|판매|메뉴', clause)):
            return False
        if re.search(r'(?:실망|후회).*?(?:법이|(?:은|는)\s*안).*?(?:없|되)', sentence):
            return False
        if re.search(r'(?:더\s*살걸|더\s*시킬|시킬껄|시킬걸|주문할껄|늦게\s*시킨|한\s*봉지|10개짜리).*?(?:후회|아쉬)', sentence):
            return False
        if re.search(r'(?:다\s*먹어|금방\s*먹어).*?아쉬', sentence):
            return False
    if guard == 'generic' and match.group() == '별로':
        after = sentence[match.end():]
        if re.match(r'\s*(?:안|없|않|(?:달|짜|크)[가-힣]{0,5}\s*않)', after):
            return False
        # "원래 떡을 별로 좋아하지 않는데 이 떡은 맛있다" is a contrast.
        if re.search(r'좋아하지\s*않는데.*(?:맛있|잘\s*먹)', after):
            return False
    if guard == 'texture':
        after = sentence[match.end():match.end()+45]
        if re.match(r'^[가-힣]{0,8}\s*(?:없이|없어|없고|없었)', after):
            return False
    return True


def classify_summary_text(text):
    """Return one exact excerpt per positive/concern theme, deterministically.

    Concern severity: 3 hygiene/spoilage claims, 2 fulfillment/packaging,
    1 sensory opinions, service/value and improvement requests. A missing
    match means no rule matched, not that the review was positive/problem-free.
    """
    # Redact before sentence splitting/windowing so a dot in an email or
    # clipped address cannot leave an identifying fragment in an excerpt.
    text = clean_summary_text(text)
    sentences = list(_sentences(text))
    positives, concerns = {}, {}
    for label, pattern, guard in POSITIVE_RULES:
        for sentence in sentences:
            match = next((m for m in pattern.finditer(sentence)
                          if _positive_allowed(sentence, m, guard)), None)
            if match:
                positives[label] = {'label': label, 'excerpt': redact_private_details(_excerpt(sentence, match))}
                break
    for theme, pattern, severity, guard in CONCERN_RULES:
        for sentence in sentences:
            match = next((m for m in pattern.finditer(sentence)
                          if _concern_allowed(sentence, m, guard)), None)
            if match:
                concerns[theme] = {'theme': theme, 'excerpt': redact_private_details(_excerpt(sentence, match)),
                                   'severity': severity}
                break
    # Specific evidence is more useful than repeating "아쉽다" from that review.
    if len(concerns) > 1:
        concerns.pop('기타 불만·아쉬움', None)
    return {'positive': list(positives.values()), 'concerns': list(concerns.values())}
