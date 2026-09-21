import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import main
from daily_report import build_report, yesterday, report_period


class DailyApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_schema2_archive_and_legacy_use_same_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old='2026-09-14'
            rows=[dict(date=old,content='맛있어요',author='a',score=5),
                  dict(date=old,content='쑥 향이 진하고 포장이 터졌어요.',author='b',score=2)]
            report=build_report({'jasaol':rows},old)
            path=root/(old+'.json')
            path.write_text(json.dumps(report),encoding='utf-8')
            before=path.read_bytes()
            current=copy.deepcopy(report);current['date']=yesterday();current.update(report_period(current['date']))
            with patch.object(main,'DAILY_REPORT_DIR',root), patch.object(main,'ensure_daily_report',AsyncMock(return_value=current)):
                history=json.loads((await main.get_daily_report(old)).body)
                latest=json.loads((await main.get_daily_report()).body)
                self.assertEqual(history['selected_count'],1)
                self.assertEqual(latest['selected_count'],1)
                self.assertEqual(history['brands'],latest['brands'])
                self.assertEqual(history['total'],2)
                self.assertTrue(history['historical'])
                self.assertEqual(path.read_bytes(),before)
                legacy=dict(report,schema_version=1)
                path.write_text(json.dumps(legacy),encoding='utf-8')
                before=path.read_bytes()
                with patch.object(main,'_load_reviews_cached',return_value={'jasaol':rows}):
                    reconstructed=json.loads((await main.get_daily_report(old)).body)
                self.assertEqual(reconstructed['selected_count'],1)
                self.assertTrue(reconstructed['reconstructed'])
                self.assertEqual(path.read_bytes(),before)

    async def test_old_sunday_rebuild_preserves_snapshot(self):
        day='2026-09-13'
        rows=[dict(date=f'2026-09-{d}',score=2,content='complaint',author=str(d)) for d in (11,12,13)]
        old=build_report({'jasaol':rows[-1:]},day)
        old['schema_version']=2
        for k in ('date_from','date_to','period_days'):old.pop(k)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/(day+'.json')
            path.write_text(json.dumps(old),encoding='utf-8');before=path.read_bytes()
            with patch.object(main,'DAILY_REPORT_DIR',root),patch.object(main,'_load_reviews_cached',return_value={'jasaol':rows}):
                result=json.loads((await main.get_daily_report(day)).body)
            self.assertEqual(result['total'],3)
            self.assertEqual(result['selected_count'],3)
            self.assertEqual(result['statistics']['total']['count'],3)
            self.assertEqual(result['date_from'],'2026-09-11')
            self.assertTrue(result['reconstructed'])
            self.assertEqual(path.read_bytes(),before)

    async def test_invalid_future_and_missing_dates(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main,'DAILY_REPORT_DIR',Path(tmp)):
            for day,code in [('bad',400),('2099-01-01',400),('2020-01-01',404)]:
                with self.assertRaises(main.HTTPException) as error:
                    await main.get_daily_report(day)
                self.assertEqual(error.exception.status_code,code)
