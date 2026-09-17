import unittest
import daily_report

class StatisticsTest(unittest.TestCase):
    def test_all_rows_and_rating_denominators(self):
        report={'brands':[{'key':'jasaol','name':'백년화편','available':True,'reviews':[
            {'score':5,'platform':'naver','excerpt':'맛있어요'},
            {'score':3,'platform':'smartstore','excerpt':'딱딱해요'},
            {'score':None,'platform':'direct','excerpt':'추천'}]},
            {'key':'myeongga','name':'명가삼대떡집','available':False,'reviews':[]}]}
        s=daily_report.statistics(report)
        self.assertEqual(s['total']['count'],3)
        self.assertEqual(s['total']['average'],4)
        self.assertEqual(s['total']['low_percent'],50)
        self.assertEqual(s['total']['unrated_count'],1)
        self.assertIn({'name':'네이버','count':2},s['brands'][0]['platforms'])
        self.assertIsNone(s['brands'][1]['count'])
        self.assertEqual(len(report['brands'][0]['reviews']),3)

    def test_server_has_no_ai_execution(self):
        from pathlib import Path
        code=Path('main.py').read_text(encoding='utf-8')
        self.assertNotIn('daily_analysis',code)
        self.assertIn("daily_report.statistics(report)",code)
