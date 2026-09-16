import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daily_report import report_dates, read_report, valid_report_date

class ArchiveTests(unittest.TestCase):
    def test_saved_history_is_listed_and_unchanged_on_read(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            old={'date':'2026-09-14','total':12,'generated_at':'2026-09-15T09:00:00+09:00'}
            path=root/'2026-09-14.json';path.write_text(json.dumps(old))
            (root/'2026-09-15.json').write_text(json.dumps({'date':'2026-09-15','total':20}))
            (root/'2026-02-30.json').write_text('{}')
            (root/'latest.json').write_text('{}')
            before=path.read_bytes();mtime=path.stat().st_mtime_ns
            self.assertEqual(report_dates(root),['2026-09-15','2026-09-14'])
            self.assertEqual(read_report(root,'2026-09-14'),old)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(path.stat().st_mtime_ns,mtime)
            with self.assertRaises(FileNotFoundError): read_report(root,'2026-09-13')
    def test_strict_dates_prevent_path_traversal(self):
        for value in ('../../memo','2026-9-01','2026-02-30','2026-09-14.json',''):
            with self.subTest(value=value),self.assertRaises(ValueError): valid_report_date(value)
    def test_payload_date_must_match_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'2026-09-14.json').write_text('{"date":"2026-09-13"}')
            with self.assertRaises(ValueError):read_report(root,'2026-09-14')
if __name__=='__main__':unittest.main()
