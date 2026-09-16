import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_report import yesterday, build_report, excerpt, highlights

class DailyReportTests(unittest.TestCase):
    def test_korea_midnight_boundary(self):
        self.assertEqual(yesterday(datetime(2026,9,16,15,0,tzinfo=timezone.utc)), '2026-09-16')
        self.assertEqual(yesterday(datetime(2026,9,16,14,59,tzinfo=timezone.utc)), '2026-09-15')

    def test_missing_data_not_zero_and_previous_day_only(self):
        rows=[{'date':'2026-09-15','score':2,'content':'딱딱해서 아쉬워요','author':'a'},
              {'date':'2026-09-16','score':5,'content':'오늘 후기','author':'b'},
              {'date':'2026-09-15','score':float('nan'),'content':'별점 미제공','author':'c'}]
        r=build_report({'jasaol':rows},'2026-09-15',{'state':'cooldown'})
        self.assertEqual(r['total'],2)
        self.assertEqual(r['brands'][0]['average'],2)
        self.assertEqual(r['low_count'],1)
        self.assertIsNone(r['brands'][3]['count'])
        self.assertIn('미확인',r['brands'][0]['coverage'])
        self.assertNotIn('오늘 후기',str(r))

    def test_duplicate_and_safe_keyword_offsets(self):
        row={'date':'2026-09-15','score':5,'content':'😀 맛있어서 재구매했어요','author':'a'}
        r=build_report({'jasaol':[row,row.copy()]},'2026-09-15')
        self.assertEqual(r['total'],1)
        selected=r['brands'][0]['reviews'][0]
        self.assertEqual(selected['excerpt'][selected['highlights'][0]['start']:selected['highlights'][0]['end']],'맛있')

    def test_excerpt_retains_late_problem_and_limits_cards(self):
        text='도입부 '*100+'곰팡이가 있어요'+ ' 끝'*100
        self.assertIn('곰팡이',excerpt(text))
        rows=[{'date':'2026-09-15','score':1 if i<4 else 5,'author':str(i),'content':('딱딱해요' if i<4 else '맛있어요')+str(i)} for i in range(10)]
        r=build_report({'jasaol':rows},'2026-09-15')
        self.assertEqual(len(r['brands'][0]['reviews']),3)
        self.assertEqual(r['brands'][0]['reviews'][-1]['score'],5)

if __name__=='__main__': unittest.main()
