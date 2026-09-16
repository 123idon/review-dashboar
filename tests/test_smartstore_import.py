import ast
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartstore_import import merge_reviews, validate_reviews


def review(**changes):
    return dict(dict(date="2026-09-16", score=5, product="떡", content="맛있어요",
                     platform="naver", author="abc***", review_no="123"), **changes)


class MergeTests(unittest.TestCase):
    def test_history_preserved_and_repeat_is_idempotent(self):
        old = review(date="2026-05-06", review_no="1")
        merged, summary = merge_reviews([old], [review(), review()])
        self.assertEqual(summary["added"], 1)
        self.assertIn(old, merged)
        again, repeated = merge_reviews(merged, [review()])
        self.assertEqual(again, merged)
        self.assertEqual((repeated["added"], repeated["updated"]), (0, 0))

    def test_legacy_match_ignores_product_and_preserves_images(self):
        old = review(product="old", images=["https://example.com/image"])
        old.pop("review_no")
        merged, summary = merge_reviews([old], [review(product="new")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["images"], old["images"])
        self.assertEqual(merged[0]["review_no"], "123")
        self.assertEqual(summary["updated"], 1)

    def test_review_id_updates_changed_content(self):
        merged, summary = merge_reviews([review()], [review(content="수정 후기")])
        self.assertEqual(summary["added"], 0)
        self.assertEqual(merged[0]["content"], "수정 후기")

    def test_empty_and_invalid_input_is_rejected(self):
        for rows in ([], [review(date="2026-02-30")], [review(score=float("nan"))],
                     [review(score=0)], [review(content=" ")], [review(platform="direct")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_reviews(rows)


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class ImportEndpointTests(unittest.TestCase):
    """Exercise actual route bodies with temporary files, without starting collectors."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        src = Path(__file__).resolve().parents[1]
        scraper = types.ModuleType("scraper")
        scraper.__dict__.update(json=json, os=os, Path=Path)
        tree = ast.parse((src / "scraper.py").read_text())
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("safe_save", "load_json")]
        exec(compile(tree, "scraper.py", "exec"), scraper.__dict__)
        previous = sys.modules.get("scraper")
        sys.modules["scraper"] = scraper
        self.addCleanup(lambda: sys.modules.pop("scraper", None) if previous is None else sys.modules.__setitem__("scraper", previous))
        self.env = dict(json=json, Path=Path, datetime=datetime, Request=Request,
                        HTTPException=HTTPException, DATA_PATH=self.root / "reviews.json",
                        SMARTSTORE_STATUS={}, merge_reviews=merge_reviews,
                        naver_auto=types.SimpleNamespace(status=lambda: {"state": "needs_login"}),
                        scheduler=types.SimpleNamespace(get_job=lambda name: None),
                        validate_reviews=validate_reviews, invalidate_cache=lambda: None)
        tree = ast.parse((src / "main.py").read_text())
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in
                     ("smartstore_chunk_path", "import_smartstore_chunk", "import_smartstore_done", "smartstore_status")]
        for node in tree.body:
            node.decorator_list = []
        exec(compile(tree, "main.py", "exec"), self.env)

    def call(self, name, *args, **kwargs):
        return asyncio.run(self.env[name](*args, **kwargs))

    def test_session_isolation_count_guard_backup_and_status(self):
        original = [review(date="2026-05-06", review_no="old")]
        path = self.root / "smartstore.json"
        path.write_text(json.dumps(original))
        for sid, rows in (("a" * 32, [review()]), ("b" * 32, [review(review_no="456", author="def***")])):
            self.call("import_smartstore_chunk", Request(dict(reviews=rows, replace=True, import_id=sid)))
        with self.assertRaises(HTTPException) as caught:
            self.call("import_smartstore_done", import_id="a" * 32, expected_count=2)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(json.loads(path.read_text()), original)
        done = self.call("import_smartstore_done", import_id="a" * 32, expected_count=1)
        self.assertEqual((done["added"], done["imported"]), (1, 2))
        self.assertEqual(json.loads(next((self.root / "smartstore_backups").glob("*.json")).read_text()), original)
        self.assertTrue((self.root / ("smartstore_chunk_" + "b" * 32 + ".json")).exists())
        state = self.call("smartstore_status")
        self.assertEqual(state["last_import"]["added"], 1)

    def test_empty_chunk_and_bad_session_do_not_touch_data(self):
        for body in (dict(reviews=[]), dict(reviews=[review()], import_id="../../bad")):
            with self.assertRaises(HTTPException) as caught:
                self.call("import_smartstore_chunk", Request(body))
            self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
