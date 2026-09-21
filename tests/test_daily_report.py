import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daily_report import yesterday, build_report, report_period, statistics

class DailyReportTests(unittest.TestCase):
    def test_monday_weekend_and_tuesday_single_day(self):
        anchor=yesterday(datetime(2026,9,20,15,0,tzinfo=timezone.utc))
        self.assertEqual(report_period(anchor),dict(date_from='2026-09-18',date_to='2026-09-20',period_days=3))
        rows=[dict(date=f'2026-09-{d}',score=2,content='complaint',author=str(d)) for d in range(17,22)]
        report=build_report({'jasaol':rows},anchor)
        self.assertEqual(report['total'],3)
        self.assertEqual(report['low_count'],3)
        self.assertEqual({r['date'] for r in report['brands'][0]['reviews']},{'2026-09-18','2026-09-19','2026-09-20'})
        self.assertEqual(statistics(report)['total']['count'],3)
        self.assertEqual(build_report({'jasaol':rows},'2026-09-21')['total'],1)
        self.assertEqual(report_period('2026-03-01')['date_from'],'2026-02-27')
        self.assertEqual(report_period('2023-01-01')['date_from'],'2022-12-30')
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
    def test_duplicate_date_filter_invalid_scores(self):
        row={'date':'2026-09-15','score':2,'content':'딱딱해서 먹기 어려워요','author':'a'}
        r=build_report({'jasaol':[row,row.copy(),dict(row,date='2026-09-16'),dict(row,author='b',score=float('nan'))]},'2026-09-15',{'state':'cooldown'})
        self.assertEqual(r['total'],2)
        self.assertEqual(r['brands'][0]['average'],2)
        self.assertEqual(r['low_count'],1)
        self.assertIn('미확인',r['brands'][0]['coverage'])
if __name__=='__main__':unittest.main()
