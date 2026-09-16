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
    def test_pairing_rejects_expired_wrong_and_consumed_codes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'DATA', Path(d)):
            digest = hashlib.sha256(b'correct').hexdigest()
            with patch.dict(os.environ, NAVER_PAIRING_SHA256=digest, NAVER_PAIRING_EXPIRES=str(time.time()+60)):
                self.assertTrue(worker.pairing_allowed('correct'))
                self.assertFalse(worker.pairing_allowed('wrong'))
                worker.private_save(Path(d)/'naver_private'/'paired.json', {'hash': digest})
                self.assertFalse(worker.pairing_allowed('correct'))
            with patch.dict(os.environ, NAVER_PAIRING_SHA256=digest, NAVER_PAIRING_EXPIRES='1'):
                self.assertFalse(worker.pairing_allowed('correct'))

    def test_auth_excludes_unrelated_sites(self):
        state = worker.filter_state({'cookies': [{'domain': '.naver.com', 'name': 'ok'},
                                                 {'domain': 'naver.com.evil.example', 'name': 'bad'}],
                                     'origins': [{'origin': 'https://sell.smartstore.naver.com'},
                                                 {'origin': 'https://example.com'}]})
        self.assertEqual(len(state['cookies']), 1)
        self.assertEqual(len(state['origins']), 1)
        with self.assertRaises(ValueError):
            worker.filter_state({'cookies': []})

    def test_session_is_private_and_status_does_not_imply_ready(self):
        with tempfile.TemporaryDirectory() as d, patch.object(worker, 'AUTH', Path(d)/'private'/'state.json'), patch.object(worker, 'STATUS', Path(d)/'status.json'):
            self.assertEqual(worker.status()['state'], 'needs_login')
            worker.private_save(worker.AUTH, {'cookies': [{'value': 'secret'}]})
            self.assertEqual(worker.AUTH.stat().st_mode & 0o777, 0o600)
            worker.record('running', 'test')
            self.assertEqual(worker.status()['state'], 'interrupted')
            self.assertNotIn('secret', json.dumps(worker.status()))

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
