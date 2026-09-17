import unittest
from review_identity import review_identity
from daily_report import build_report

class IdentityTests(unittest.TestCase):
    def test_distinct_reviews_with_same_masked_author_and_text_survive(self):
        row=dict(date='2026-09-16',author='김**',content='맛있어요',score=5,platform='direct')
        a=dict(row,review_no='1'); b=dict(row,review_no='2')
        c=dict(a,platform='smartstore')
        self.assertEqual(len({review_identity(x) for x in [a,b,c,a.copy()]}),3)
        report=build_report({'jasaol':[a,b,c,a.copy()]},'2026-09-16')
        self.assertEqual(report['total'],3)

    def test_legacy_identity_uses_full_body_and_product(self):
        a=dict(date='2026-09-16',author='김**',content='가'*100+'첫 후기',product='A')
        b=dict(a,content='가'*100+'다른 후기')
        c=dict(a,product='B')
        self.assertEqual(len({review_identity(x) for x in [a,b,c,a.copy()]}),3)
