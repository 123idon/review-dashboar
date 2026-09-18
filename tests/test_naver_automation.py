import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import naver_automation as worker


class AutomationTests(unittest.TestCase):
    def test_status_never_requests_an_account_and_keeps_cooldown(self):
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'STATUS', Path(d)/'status.json'), patch.dict(os.environ, NAVER_PUBLIC_NOT_BEFORE='0'):
            self.assertEqual(worker.status()['state'], 'pending')
            self.assertFalse(worker.status()['account_required'])
            worker.record('blocked', 'limited', retry_at=time.time()+3600)
            self.assertEqual(worker.status()['state'], 'cooldown')
            self.assertFalse(worker.status()['session_configured'])
            worker.private_save(worker.STATUS, {'mode':'seller', 'state':'ready', 'last_success':'2026-09-16'})
            self.assertEqual(worker.status()['state'], 'pending')
            self.assertNotIn('last_success', worker.status())

    def test_real_export_parser_handles_lying_dimensions(self):
        from openpyxl import Workbook
        from zipfile import ZipFile, ZIP_DEFLATED
        import re
        with tempfile.TemporaryDirectory() as d:
            original = Path(d)/'original.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(['리뷰등록일', '구매자평점', '상품명', '리뷰상세내용', '등록자', '리뷰글번호'])
            sheet.append(['2026.09.16. 17:49:52', 5, '떡', '맛있어요', 'masked', 123])
            workbook.save(original)
            path = Path(d)/'naver.xlsx'
            with ZipFile(original) as src, ZipFile(path, 'w', ZIP_DEFLATED) as dest:
                for name in src.namelist():
                    data = src.read(name)
                    if name == 'xl/worksheets/sheet1.xml':
                        data = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1"', data)
                    dest.writestr(name, data)
            rows = worker.parse_export(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['date'], '2026-09-16')
            self.assertEqual(rows[0]['review_no'], '123')


if __name__ == '__main__':
    unittest.main()


class HealthTests(unittest.TestCase):
    def test_failed_collection_is_not_healthy_just_because_import_is_recent(self):
        from datetime import datetime, timezone
        for state in ('not_allowed','blocked','error','pending','cooldown'):
            health=worker.collection_health({'state':state},'2026-09-17',datetime(2026,9,17,16,tzinfo=timezone.utc))
            self.assertTrue(health['stalled'])
            self.assertFalse(health['collection_verified'])
            self.assertEqual(health['days_since'],1)
            self.assertEqual(health['data_freshness'],'recent')
    def test_success_with_no_new_reviews_is_distinct_from_stale_data(self):
        from datetime import datetime
        health=worker.collection_health({'state':'ready','last_success':'2026-09-18'},'2026-09-10',datetime(2026,9,18))
        self.assertFalse(health['stalled'])
        self.assertEqual(health['data_freshness'],'stale')
