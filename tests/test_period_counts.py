import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
import analyzer
import scraper
import main


class PeriodTests(unittest.TestCase):
    def test_seven_complete_korean_calendar_days(self):
        rows=[dict(date=f'2026-09-{d:02}',score=5) for d in range(9,18)]
        r=analyzer.compute_stats(rows,clock=datetime(2026,9,16,15,1,tzinfo=timezone.utc))
        self.assertEqual((r['week_from'],r['week_to'],r['week_count']),('2026-09-10','2026-09-16',7))
        r=analyzer.compute_stats(rows,'2026-09-15','2026-09-17')
        self.assertEqual((r['total_count'],r['week_count']), (3,3))
        self.assertEqual((r['week_from'],r['week_to']),('2026-09-15','2026-09-17'))

    def test_stats_list_distribution_and_platform_counts_agree(self):
        rows=[dict(date='2026-09-15',score='2',content=str(i),platform='direct') for i in range(620)]
        rows += [dict(date='2026.09.16',score=5,platform='smartstore'),dict(date=None,score=5),dict(date='2026-09-17',score=None)]
        for start,end in [(None,None),('2026-09-15','2026-09-15'),(None,'2026-09-15'),('2026-09-16',None),('2020-01-01','2020-01-02')]:
            with self.subTest(start=start,end=end):
                stats=analyzer.compute_stats(rows,start,end)
                page=analyzer.get_reviews_page(rows,start,end,size=10000)
                low=analyzer.get_reviews_page(rows,start,end,filter_type='low')
                self.assertEqual(stats['total_count'],page['total'])
                self.assertEqual(stats['total_negative'],low['total'])
                self.assertEqual(sum(x['count'] for x in stats['platform_stats'].values()),page['total'])
                self.assertEqual(sum(x['count'] for x in stats['weekly_trend']),page['total'])
        self.assertEqual(analyzer.compute_stats(rows)['total_count'],622)
        self.assertEqual(len(analyzer.compute_stats(rows)['reviews']),500)
        self.assertEqual(analyzer.get_reviews_page(rows,size=100,page=7)['total'],622)

    def test_invalid_ranges_and_pagination_rejected(self):
        for start,end in [('2026-09-17','2026-09-14'),('bad',None),(None,'2026-02-30'),('2099-01-01',None)]:
            with self.assertRaises(ValueError):analyzer.compute_stats([],start,end)
            with self.assertRaises(main.HTTPException) as exc:asyncio.run(main.get_data(start,end))
            self.assertEqual(exc.exception.status_code,400)
            with self.assertRaises(main.HTTPException) as exc:asyncio.run(main.get_reviews(date_from=start,date_to=end))
            self.assertEqual(exc.exception.status_code,400)
        with self.assertRaises(ValueError):analyzer.get_reviews_page([],size=0)


class PreservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_file_classifies_naver_import_without_changing_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=root/'reviews.json';base=root/'jasaol_base.json';new=root/'jasaol_new.json'
            raw.write_text('{}');new.write_text('[]')
            direct=dict(date='2026-09-15',content='Naver Pay on direct store',platform='naver',score=5)
            imported=dict(date='2026-09-15',content='Naver store',platform='naver',score=3)
            base.write_text(json.dumps([direct]));(root/'smartstore.json').write_text(json.dumps([imported]))
            main.invalidate_cache()
            try:
                with patch.object(main,'DATA_PATH',raw),patch.object(scraper,'JASAOL_BASE_PATH',base),patch.object(scraper,'JASAOL_NEW_PATH',new):
                    cache=main._load_reviews_cached()
                self.assertEqual(analyzer.get_reviews_page(cache['jasaol'],filter_type='ss')['total'],1)
                self.assertEqual(analyzer.get_reviews_page(cache['jasaol'],filter_type='jasa')['total'],1)
                self.assertEqual(json.loads((root/'smartstore.json').read_text()),[imported])
            finally:main.invalidate_cache()

    async def test_recovery_can_resume_and_reports_cutoff_completion(self):
        from datetime import timedelta
        cutoff=(datetime.now(analyzer.KST)-timedelta(days=14)).date()
        row=dict(date=(cutoff-timedelta(days=1)).isoformat(),review_no='old')
        audit={}
        with patch.object(scraper,'fetch_review_page',AsyncMock(return_value=(20,[row],0))) as fetch:
            self.assertEqual(await scraper.scrape_jasaol_recent(14,audit=audit,start_page=20),[])
        self.assertTrue(audit['complete'])
        self.assertEqual(fetch.call_args.args[2],20)

    async def test_incremental_collection_never_discards_previous_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            new=root/'jasaol_new.json'
            old=[dict(date='2026-09-14',author='a',content='old review',score=5),dict(date='2026-09-15',author='b',content='yesterday',score=4)]
            new.write_text(json.dumps(old),encoding='utf-8')
            fresh=dict(date='2026-09-17',author='c',content='new review',score=3)
            with patch.object(scraper,'JASAOL_NEW_PATH',new),patch.object(scraper,'DATA_PATH',root/'reviews.json'),patch.object(scraper,'scrape_jasaol_incremental',AsyncMock(side_effect=[[fresh],[]])):
                await scraper.collect_all(only_jasaol=True)
                await scraper.collect_all(only_jasaol=True)
            self.assertEqual(json.loads(new.read_text(encoding='utf-8')),old+[fresh])

    async def test_repair_retains_existing_data_and_takes_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'jasaol_base.json';new=root/'jasaol_new.json'
            old=dict(date='2026-01-01',content='history',review_no='old')
            fresh=dict(date='2026-09-15',content='recovered',review_no='new')
            base.write_text(json.dumps([old]));new.write_text('[]')
            with patch.object(main,'DATA_PATH',root/'reviews.json'),patch.object(scraper,'JASAOL_BASE_PATH',base),patch.object(scraper,'JASAOL_NEW_PATH',new),patch.object(scraper,'scrape_jasaol_recent',AsyncMock(return_value=[fresh])):
                r=await main.refresh_jasaol_recent(14)
            self.assertEqual(r['added'],1)
            self.assertEqual(json.loads(base.read_text()),[old])
            self.assertEqual(json.loads(new.read_text()),[fresh])
            self.assertEqual(len(list((root/'jasaol_backups').glob('*.json'))),2)
