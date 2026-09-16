import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daily_report import yesterday, build_report, highlights

class DailyReportTests(unittest.TestCase):
    def test_korea_midnight_boundary(self):
        self.assertEqual(yesterday(datetime(2026,9,16,15,0,tzinfo=timezone.utc)), '2026-09-16')
        self.assertEqual(yesterday(datetime(2026,9,16,14,59,tzinfo=timezone.utc)), '2026-09-15')
    def test_two_brands_all_rows_and_full_content(self):
        long='맛있어요. '*100+'포장이 터져 떡이 밖으로 나왔어요.'
        rows=[{'date':'2026-09-15','score':5,'content':long+str(i),'author':str(i)} for i in range(40)]
        r=build_report({'jasaol':rows,'myeongga':[rows[0]],'papa':rows,'changeok':rows},'2026-09-15')
        self.assertEqual([b['key'] for b in r['brands']],['jasaol','myeongga'])
        self.assertEqual(r['total'],41)
        self.assertEqual(len(r['brands'][0]['reviews']),40)
        self.assertEqual(r['brands'][0]['reviews'][0]['excerpt'],long+'10')
        self.assertTrue(all(not v['highlights'] for b in r['brands'] for v in b['reviews']))
    def test_generic_praise_and_negated_problems_are_not_marked(self):
        for text in ('추천해요. 맛있어요. 만족합니다. 재구매할게요.', '곰팡이 없어요.', '파손 없이 잘 도착했어요.', '딱딱하지 않아요.', '배송이 늦지 않아서 좋아요.', '예상했던것보다 맛있습니다', '빠르게 배송해주셔서 감사합니다 ^^'):
            self.assertEqual(highlights(text),[],text)
    def test_actionable_clause_is_highlighted_not_just_keyword(self):
        text='😀 추천해요. 포장이 터져 떡이 밖으로 나왔어요. 배송 포장을 개선해 주세요.'
        spans=highlights(text)
        self.assertEqual(len(spans),2)
        self.assertIn('떡이 밖으로',text[spans[0]['start']:spans[0]['end']])
        self.assertNotIn('추천해요',text[spans[0]['start']:spans[0]['end']])
        self.assertEqual(spans[0]['reason'],'배송·포장')
    def test_duplicate_date_filter_invalid_scores(self):
        row={'date':'2026-09-15','score':2,'content':'딱딱해서 먹기 어려워요','author':'a'}
        r=build_report({'jasaol':[row,row.copy(),dict(row,date='2026-09-16'),dict(row,author='b',score=float('nan'))]},'2026-09-15',{'state':'cooldown'})
        self.assertEqual(r['total'],2)
        self.assertEqual(r['brands'][0]['average'],2)
        self.assertEqual(r['low_count'],1)
        self.assertIn('미확인',r['brands'][0]['coverage'])
if __name__=='__main__':unittest.main()
