import unittest
from review_types import classify,type_statistics
class ReviewTypesTest(unittest.TestCase):
 def test_samples(self):
  for text,expected in [('흑임자는 한쪽이 딱딱했어요 ㅠ','구체적 불만 표현'),('퀵배송 주문했는데 아주 빨리 도착했어요','배송·수령'),('많이 안달고 쫀득한 떡에 고소한 흑임자가 잘 어우러져 맛있어요','당도'),('쿠폰 행사 많이 해주세요','개선 요청'),('맛있어요 추천해요','일반 칭찬·만족')]:
   self.assertIn(expected,classify(text))
  self.assertNotIn('구체적 불만 표현',classify('딱딱하지 않아요'))
  self.assertNotIn('구체적 불만 표현',classify('먹을때마다 느끼지만 진짜 맛있어요'))
  self.assertEqual(classify(''),{'본문 없음':''})
 def test_overlap_once_and_exact_evidence(self):
  rows=[{'excerpt':'배송 배송 빨라요 포장 좋아요'},{'excerpt':'맛있어요'}]
  s=type_statistics({'brands':[{'key':'jasaol','name':'백년화편','reviews':rows}]})
  self.assertEqual(s['total'],2)
  d={r['name']:r for r in s['rows']}
  self.assertEqual(d['배송·수령']['count'],1)
  self.assertEqual(d['포장·보냉']['percent'],50)
  self.assertEqual(d['일반 칭찬·만족']['count'],1)
  for r in s['rows']:
   for e in r['examples']: self.assertIn(e['phrase'],e['text'])
