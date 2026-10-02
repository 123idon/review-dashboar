import unittest

from review_summary_phrases import classify_summary_text, redact_private_details, clean_summary_text


class SummaryPhraseTests(unittest.TestCase):
    def labels(self, text):
        result = classify_summary_text(text)
        return {x['label'] for x in result['positive']}, {x['theme'] for x in result['concerns']}

    def test_no_rating_input_and_three_star_praise(self):
        text = '순식간에 다 먹어 버려서 하나밖에 안 남았네요~~^^ 아마 단언컨대 전 세계에서 제일 맛있는 떡일 겁니다!!!'
        positive, concerns = self.labels(text)
        self.assertIn('맛·향 만족', positive)
        self.assertEqual(concerns, set())

    def test_actual_five_star_hardness(self):
        text = '추석명절 맞이해서 친정엄마네와 저희집에서 먹으려고 각각 배송받았는데 받자마자 먹을분량 제외후 냉동했는데 그 다음 해동후에 사진처럼 일부분은 말랑하게 해동되는데 반이상이 딱딱해서 정말 짜증이....'
        positive, concerns = self.labels(text)
        self.assertIn('해동·식감 아쉬움', concerns)
        self.assertNotIn('기타 불만·아쉬움', concerns)

    def test_negated_and_expected_defects_are_not_concerns(self):
        for text in [
            '냉동실에 넣어 해동해도 딱딱하지 않아요',
            '안 질기고 고소해요', '퍽퍽함이 없어서 좋아요',
            '불만 없어요', '불만은 없어요', '불편하지 않아요',
            '비싸지 않아요', '비싸진 않아요', '별로 안 달아요',
            '배송 늦지 않고', '딱딱하지 않아', '이물질 없이',
            '냉동떡이라 질길 줄 알았는데 쫀득해서 놀랐어요.',
            '식으면 딱딱해지기 마련인데 이 떡은 그런 부분 없이 부드럽고 맛있습니다.',
            '설기라서 딱딱할줄알았는데 촉촉함에 놀랐습니다 또 설기는 건조함 때문에 삼킴이 어려운적이 많았는데 호박 때문인지 퍽퍽함이 없어서 전자레인지 없이 실온에서 무리없이 먹기 가능하였습니다',
            '아이스팩도 안녹게 꼼꼼하게 넣어주셨어요',
            '상상한맛 그대로 에요', '예상했던것보다 맛있습니다',
            '맛좋아요 두번구매했음 좀 쉬었다 주문할께요',
            '코코넛가루 냄새도 나서 순삭입니다~',
            '이물질이 나왔다는 후기를 봤는데 걱정 없었어요',
            '콩이 종류별로 다양하게 들엇서 달지 않고 맛있어요',
            '콩도 종류별로 정말 많이 들어있고 너무 짜거나 달지 않아서 슴슴하면서도 좋아요',
            '별로 달지 않아서 좋아요',
            '단맛이 없고 콩이 많이 들어가서 식감이 좋아요',
            '입맛없을때 하나씩 꺼내먹으니 든든해요',
            '너무달콤 꼬소해서 좋아요', '많이 달아서 만족스러워요',
            '많이 달지 안고 너무 좋아요', '딱딱 하지않아서 좋아요',
            '맛이 없을 수가 없잖아요', '맛없는 떡이 없네요',
            '인위적인 맛 없이 순수담백한 맛이라 너무좋아요',
            '제조한날 배송시작하고 다음날 바로 받았어요.',
            '포장도 꼼꼼하게 해주시고 좋아요!!!',
            '제주문했네요 어려서 먹었던 모시떡',
            '대월떡집에 빠져서 다른떡을 먹지못하고있네요',
            '옥수수떡에빠져서 어디서시켰냐며 명가삼대 떡집을 널리알리는중입니다.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(classify_summary_text(text)['concerns'], [])

    def test_negated_praise_and_conditional_praise(self):
        for text in ['쫀득하지 않아요', '맛있지 않아요', '고소함이 없어요',
                     '전혀 부드럽지 않아요', '맛있을 것 같아요',
                     '재구매는 안 할 것 같아요', '재주문 할 의향 없어요', '재구매 안 할래요',
                     '견과류가 많이 들어있지는 않아 별하나 뺐어요',
                     '재구매할 생각이 없습니다', '재주문은 하지 않는걸로',
                     '개별포장이라 불편하고 뜯기 힘들어요',
                     '밤이 너무 많아서 느끼해요', '맛도 다른곳보다 그닥 맛있다고 볼수없음']:
            with self.subTest(text=text):
                self.assertEqual(classify_summary_text(text)['positive'], [])

    def test_actual_serious_claims(self):
        cases = [
            ('밤이 중요한데 하나같이 밤이 다 썩었어요', '변질·이취 관련 언급'),
            ('첫 봉지에서 긴 머리카락이 나왔네요', '이물·위생 관련 언급'),
            ('포장상태가 너무 비위생적이네요.', '이물·위생 관련 언급'),
            ('이번건 아이스팩은 다 녹고 떡도 축축하게 젖어서 뜯어보니까 꾸린내나네요.', '변질·이취 관련 언급'),
            ('호박에서 나는 이냄새의 정체는 뭘까요?', '변질·이취 관련 언급'),
        ]
        for text, theme in cases:
            with self.subTest(text=text):
                concern = next(x for x in classify_summary_text(text)['concerns'] if x['theme'] == theme)
                self.assertEqual(concern['severity'], 3)

    def test_high_rating_melt_and_packaging_variants(self):
        for text in [
            '그냥 떡만 녹아서온거 빼고는 다좋음!!!',
            '잘 받았습니다. 날이 더워서 다 녹아서 왓긴해도 맛잇을거 같아요.',
            '떡이 다 녹아서 오긴 햇지만 맛은 좋으네요.',
            '녹아서 와서 다시 얼렸다가 먹어도 식감 괜찮나 싶었는데 쫀딕하고 아주 맛있어요',
            '아이스팩이 다 터져서 안에까지 들어갔네요 ㅠ',
        ]:
            with self.subTest(text=text):
                self.assertIn('보냉·해동 상태', self.labels(text)[1])
        self.assertIn('포장 파손·내용물 누출', self.labels('또..하나가 터져서 왔어요. 그치만 맛은 있어요!')[1])
        self.assertEqual(classify_summary_text('입안에서 살살 녹아요')['concerns'], [])
        self.assertEqual(classify_summary_text('옥수수 알갱이가 톡톡 터져요')['concerns'], [])

    def test_improvement_requests_are_not_praise(self):
        for text in [
            '무당저염떡도 제발 만들어 주세요.',
            '영양찰떡만따로해주세요 양이작아요!',
            '덜 달았으면 좋겠어요', '당도를 좀 줄여주세요',
        ]:
            with self.subTest(text=text):
                self.assertIn('개선·선택지 요청', self.labels(text)[1])
        self.assertNotIn('과하지 않은 단맛', self.labels('덜 달았으면 좋겠어요')[0])
        self.assertEqual(classify_summary_text('많이 파세요')['concerns'], [])

    def test_specific_grounded_positive_themes(self):
        cases = [
            ('많이 달지 않아서 아침 식사로도 좋습니다.', {'과하지 않은 단맛', '간편한 식사·간식'}),
            ('선물로 좋고 개별포장이라 하나씩 꺼내 먹기 편하고 맛있어요', {'포장 만족·개별포장 편의'}),
            ('떡에 밤이 진짜 많구 쑥향이 진하게 살아있어요', {'풍성한 재료·속', '맛·향 만족'}),
            ('부드럽고 적당히 달콤하고 식어도 쫀득하고 굳지 않더라구요', {'쫀득·부드러운 식감', '과하지 않은 단맛'}),
            ('매번 주문해서 먹고 있어요.', {'재구매·반복 이용'}),
            ('냉동떡이라 질길 줄 알았는데 쫀득해서 놀랐어요.', {'쫀득·부드러운 식감'}),
            ('딱딱할줄알았는데 촉촉함에 놀랐습니다', {'쫀득·부드러운 식감'}),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(expected <= self.labels(text)[0])

    def test_mixed_reviews_keep_both_and_independent_sentences(self):
        result = classify_summary_text('쫀득하고 맛있어요. 그런데 포장이 터져서 왔어요.')
        self.assertIn('쫀득·부드러운 식감', {x['label'] for x in result['positive']})
        self.assertIn('포장 파손·내용물 누출', {x['theme'] for x in result['concerns']})
        self.assertEqual(classify_summary_text('냉동떡이라 질길 줄 알았는데 쫀득했어요. 하지만 가운데는 딱딱했어요.')['concerns'][0]['theme'], '해동·식감 아쉬움')

    def test_each_theme_once_excerpts_are_source_substrings(self):
        text = '😀 쫀득하고 부드럽고 정말 쫀득해요! 포장이 터졌어요. 또 포장이 터져서 왔어요.\n(2026-09-30 14:35:00 에 등록된 네이버 페이 구매평)'
        result = classify_summary_text(text)
        for key, field in [('positive', 'label'), ('concerns', 'theme')]:
            self.assertEqual(len(result[key]), len({x[field] for x in result[key]}))
            for item in result[key]:
                self.assertIn(item['excerpt'], text)
                self.assertNotIn('네이버 페이 구매평', item['excerpt'])
                self.assertGreater(len(item['excerpt']), 8)
        self.assertEqual(result, classify_summary_text(text))

    def test_long_review_excerpt_keeps_nearby_context(self):
        text = '앞 이야기입니다 ' * 60 + '냉동했다 해동했는데 가운데가 딱딱했어요 그래서 아쉬워요 ' + '뒤 이야기입니다 ' * 60
        result = classify_summary_text(text)
        excerpt = next(x['excerpt'] for x in result['concerns'] if x['theme'] == '해동·식감 아쉬움')
        self.assertIn(excerpt, text)
        self.assertIn('냉동했다 해동했는데 가운데가 딱딱했어요', excerpt)
        self.assertLessEqual(len(excerpt), 220)

    def test_redacts_private_details_without_prices_or_products(self):
        # Synthetic examples only; no real customer contact details are fixtures.
        text = '010-0000-0000 example@example.com 서울시 강남구 예시로 123 101동 202호 35,000원 콩떡 20개'
        safe = redact_private_details(text)
        self.assertNotIn('010-0000-0000', safe)
        self.assertNotIn('example@example.com', safe)
        self.assertNotIn('예시로 123', safe)
        self.assertNotIn('101동 202호', safe)
        self.assertIn('35,000원 콩떡 20개', safe)
        self.assertEqual(redact_private_details('선물로 35,000원 콩떡으로 20개 구입'), '선물로 35,000원 콩떡으로 20개 구입')
        self.assertEqual(clean_summary_text('맛있어요 (2026-09-30 14:35:00 에 등록된 네이버 페이 구매평)'), '맛있어요')
        self.assertEqual(redact_private_details('2026-09-30 콩떡 10개 23000원'), '2026-09-30 콩떡 10개 23000원')
        result = classify_summary_text('맛있어요 연락처 010-0000-0000. 포장이 터졌어요 example@example.com')
        self.assertTrue(result['positive'])
        self.assertTrue(result['concerns'])
        self.assertNotIn('010-0000-0000', str(result))
        self.assertNotIn('example@example.com', str(result))
        self.assertNotIn('@', str(result))

    def test_empty_unclassified_and_metadata_only(self):
        for text in [None, '', '   ', '배송', '포장', '쑥', '(2026-09-30 14:35:00 에 등록된 네이버 페이 구매평)']:
            self.assertEqual(classify_summary_text(text), {'positive': [], 'concerns': []})


if __name__ == '__main__':
    unittest.main()
