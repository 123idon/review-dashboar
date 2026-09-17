import copy
import unittest
from daily_report import build_report
from review_selection import highlights, select_report


class SelectionTests(unittest.TestCase):
    def test_positive_sensory_reviews_do_not_qualify(self):
        for text in ['쫄깃하다', '고소하다', '쫀득쫀득 정말 맛있어요 담에 또 구매할게요~',
                     '말랑말랑 쫀든쫀득 진짜 굳지않고 좋아요.',
                     '밥알이 씹히는 식감이 좋았다', '쑥 향이 진하다',
                     '촉촉하고 부드러워요', '담백하며 맛도 깔끔해요',
                     '적당히 달아서 좋다', '적당한 당도와 달짝지근한 맛',
                     '딱딱하지 않아요', '안 질기고 고소해요',
                     '이빨에 눌러붙지않은 쫀쫀함']:
            with self.subTest(text=text): self.assertEqual(highlights(text), [])

    def test_concrete_negative_sensory_evidence_qualifies(self):
        for text in ['해동해도 가운데가 딱딱했다', '퍽퍽해서 목이 막혀요',
                     '질겨서 씹기 어려워요', '너무 달아서 물려요', '너무 짜요',
                     '텁텁한 맛이 남아요', '쫄깃하지 않아서 아쉬워요',
                     '고소함이 없고 쑥 향이 약해요', '부드럽지 않아요',
                     '쓴맛이 나요', '떡이 서로 붙어 분리할 수 없어요']:
            with self.subTest(text=text): self.assertTrue(highlights(text))

    def test_mixed_review_keeps_body_but_only_useful_highlights(self):
        for text, expected in [
            ('쫄깃하고 고소하지만 많이 달지 않아서 좋아요', ['많이 달지 않아서']),
            ('고소하고 쑥 향이 진해요. 포장이 터졌어요.', ['포장이 터졌어요']),
            ('쫄깃하지만 가운데가 딱딱했어요', ['딱딱했어요']),
        ]:
            with self.subTest(text=text):
                self.assertEqual([text[h['start']:h['end']] for h in highlights(text)], expected)

    def test_actual_generic_reviews_excluded(self):
        for text in ['맛있어요', '추천해요', '좋아요', '별로예요',
                     '선물로 보냈는데 너무 맛있다고 하네요',
                     '빠른배송 감사합니다..', '배송빠르게 잘 받았습니다 다음에도 구매할게요',
                     '맛도 굿~ 배송도 굿입니다. ^^', '기대를 많이 했었나봐요.',
                     '이번엔 흑임자로 구매했는데 이것도 맛있네요',
                     '쑥 콩달떡요번에주문했는데 너무마음에들었네요 크기도 맛도 훌륭했어요 최고!!',
                     '맛이 좋아요', '쑥향을 잊지 못해 다시 구매하는 밥알찹쌀떡 입니다.']:
            with self.subTest(text=text): self.assertEqual(highlights(text), [])

    def test_positive_negative_mixed_and_actual_variants(self):
        for text in ['많이 달지 않아서 좋았다', '너무 달지는 않아요', '해동해도 가운데가 딱딱했다',
                     '포장이 터져 있었다', '떡이 서로 붙어 분리하기 어려웠다',
                     '맛있지만 포장이 터졌어요', '달지않고너무맛있다고',
                     '진한 쑥향에 덜 달달한 팥소의 조화로 즐겨 먹는 떡입니다',
                     '아이스빽도없이왔는데 떡이안상했을지신경쓰이네요ㅠㅠ',
                     '밥알도 살아있고 팥도 달지않고 맛있어요',
                     '안으로 들어갈수록 콩이 점점더 많아지는 마법의 콩떡입니다',
                     '지정날짜 다음날 초저녁쯤 도착 문자가 오더라고요',
                     '친절하게 끝까지 상담해주셔서 너무감사합니다',
                     '떡이 굳어서 왔어요~딱딱해서 선물로 주문 한 것 취소했습니다~~']:
            with self.subTest(text=text): self.assertTrue(highlights(text))

    def test_exact_spans_unicode_negation_and_no_generic_tail(self):
        text = '😀 맛있어요. 많이 달지 않아서 좋았다. 추천해요'
        spans = highlights(text)
        self.assertEqual([text[h['start']:h['end']] for h in spans], ['많이 달지 않아서'])
        text = '달지않고너무맛있다고'
        self.assertEqual(text[highlights(text)[0]['start']:highlights(text)[0]['end']], '달지않고')
        text = '딱딱하지 않아요.'
        self.assertEqual(highlights(text), [])

    def test_projection_preserves_original_stats_full_bodies_and_order(self):
        day = '2026-09-14'
        bodies = ['맛있어요', '포장이 터졌어요', '😀 달지 않아서 좋아요. ' + '맛있어요 '*100]
        rows = [dict(date=day, content=t, author=str(i), score=5) for i,t in enumerate(bodies)]
        stored = build_report({'jasaol':rows}, day)
        before = copy.deepcopy(stored)
        view = select_report(stored)
        self.assertEqual(stored,before)
        self.assertEqual(view['total'],3)
        self.assertEqual(view['selected_count'],2)
        self.assertEqual(view['brands'][0]['count'],3)
        self.assertEqual([v['excerpt'] for v in view['brands'][0]['reviews']], [bodies[2],bodies[1]])
        self.assertEqual(select_report(view),view)

    def test_all_spans_ordered_in_bounds_and_not_limited_to_two(self):
        text='달지 않고 딱딱하고 쑥 향이 약해요. 포장이 터졌어요.'
        spans=highlights(text)
        self.assertGreaterEqual(len(spans),4)
        end=0
        for h in spans:
            self.assertGreaterEqual(h['start'],end)
            self.assertGreater(h['end'],h['start'])
            self.assertLessEqual(h['end'],len(text))
            end=h['end']

if __name__ == '__main__': unittest.main()
