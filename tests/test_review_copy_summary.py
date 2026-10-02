import copy
import json
import unittest
from unittest.mock import patch

from review_copy_summary import build_copy_summary, scoped_rows, period_title, _representatives


DAY = '2026-09-30'


def review(**kwargs):
    return dict(date=DAY, content='맛있어요', score=5, platform='direct', **kwargs)


class CopySummaryTests(unittest.TestCase):
    def test_counts_use_all_rows_and_keep_anonymous_duplicates(self):
        rows = [review() for _ in range(1201)]
        report = build_copy_summary({'myeongga': rows}, DAY, DAY, 'myeongga')
        self.assertEqual(report['total_count'], 1201)
        self.assertEqual(report['brands'][0]['count'], 1201)
        self.assertEqual(report['brands'][0]['average'], 5)
        self.assertIn('1,201건', report['text'])

    def test_source_ids_deduplicate_without_merging_different_sources(self):
        rows = [review(review_no='a'), review(review_no='a'), review(review_no='b'),
                dict(review(review_no='a'), platform='smartstore'), review(), review()]
        self.assertEqual(len(scoped_rows(rows, 'jasaol', DAY, DAY)), 4)
        self.assertEqual(len(scoped_rows(rows, 'myeongga', DAY, DAY)), 5)

    def test_own_source_payment_providers_and_smartstore_separation(self):
        rows = [dict(review(review_no=str(i)), platform=platform)
                for i, platform in enumerate(['direct', 'naver', 'kakao', 'smartstore'])]
        result = build_copy_summary({'jasaol': rows}, DAY, DAY, 'jasaol')
        self.assertEqual(result['total_count'], 3)
        self.assertIn('자사몰', result['text'])

    def test_invalid_scores_are_excluded_from_metrics_but_not_text(self):
        rows = [dict(review(), score=value) for value in [5, 3, 0, None, 6, 'bad']]
        rows[2]['content'] = '떡에서 곰팡이가 나왔어요'
        result = build_copy_summary({'myeongga': rows}, DAY, DAY, 'myeongga')
        brand = result['brands'][0]
        self.assertEqual((brand['count'], brand['rated_count'], brand['excluded_count']), (6, 2, 4))
        self.assertEqual((brand['average'], brand['low_count'], brand['low_percent']), (4, 1, 50))
        self.assertIn('4건 제외', brand['text'])
        self.assertIn('곰팡이', brand['text'])
        self.assertIn('고객의 표현', result['text'])

    def test_three_star_praise_is_not_a_complaint_and_five_star_problem_is(self):
        rows = [dict(review(review_no='low-praise'), score=3,
                     content='전 세계에서 제일 맛있는 떡일 겁니다!!!'),
                dict(review(review_no='high-concern'), content='해동 후 반 이상이 딱딱해요')]
        brand = build_copy_summary({'jasaol': rows}, DAY, DAY, 'jasaol')['brands'][0]
        self.assertEqual(brand['low_count'], 1)
        self.assertEqual(brand['concern_count'], 1)
        self.assertEqual(brand['positive_low_count'], 1)
        self.assertEqual(brand['concerns'][0]['score'], 5)
        self.assertIn('별점·본문 확인', brand['text'])

    def test_brand_range_and_empty_all_invalid_states(self):
        cache = {'jasaol': [review()], 'myeongga': [dict(review(), date='2026-09-01')]}
        self.assertEqual(build_copy_summary(cache, DAY, DAY)['total_count'], 1)
        self.assertEqual(build_copy_summary(cache, '2026-09-01', DAY, 'myeongga')['total_count'], 1)
        empty = build_copy_summary(cache, '2026-08-01', '2026-08-31')
        self.assertEqual(empty['total_count'], 0)
        self.assertIn('미수집', empty['text'])
        invalid = build_copy_summary({'myeongga': [dict(review(), score=0)]}, DAY, DAY, 'myeongga')
        self.assertIsNone(invalid['brands'][0]['average'])
        self.assertIsNone(invalid['brands'][0]['low_percent'])
        self.assertIn('산출 불가', invalid['text'])

    def test_title_and_validation(self):
        self.assertEqual(period_title(DAY, DAY), '[9/30 후기 요약]')
        self.assertEqual(period_title('2026-09-01', DAY), '[9/1~9/30 후기 요약]')
        self.assertIn('2025-12-31~2026-01-01', period_title('2025-12-31', '2026-01-01'))
        for start, end, brand in [(None, DAY, 'all'), ('2026-09-31', DAY, 'all'),
                                  (DAY, '2026-09-01', 'all'), (DAY, DAY, 'unknown'),
                                  ('2099-01-01', '2099-01-02', 'all')]:
            with self.assertRaises(ValueError):
                build_copy_summary({}, start, end, brand)

    def test_no_source_mutation(self):
        cache = {'jasaol': [review()], 'myeongga': [review()]}
        before = copy.deepcopy(cache)
        build_copy_summary(cache, DAY, DAY)
        self.assertEqual(cache, before)

    def test_representatives_keep_distinct_serious_claims_and_high_stars(self):
        candidates = [
            dict(_index=0, date='2026-09-23', score=1, severity=3, theme='위생', excerpt='비위생적이네요'),
            dict(_index=1, date='2026-09-24', score=1, severity=3, theme='위생', excerpt='머리카락이 나왔어요'),
            dict(_index=2, date='2026-09-23', score=1, severity=3, theme='변질', excerpt='꾸린내가 나요'),
            dict(_index=3, date='2026-09-25', score=1, severity=3, theme='변질', excerpt='밤이 썩었어요'),
        ] + [dict(_index=i, date=DAY, score=1, severity=1, theme=f'일반{i}', excerpt='불편')
             for i in range(4, 14)] + [dict(_index=14, date=DAY, score=5, severity=2,
                                          theme='보냉', excerpt='아이스팩이 녹아서 왔어요')]
        selected = _representatives(candidates)
        text = str(selected)
        self.assertEqual(len(selected), 8)
        self.assertIn('머리카락', text)
        self.assertIn('썩었', text)
        self.assertIn('꾸린내', text)
        self.assertTrue(any(r['score'] == 5 for r in selected))
        self.assertNotIn('_index', text)

    def test_unclassified_fallback_hides_private_details_and_import_footer(self):
        row = dict(review(), score=2, content='연락 010-1234-5678 / person@example.com\n'
                   '(2026-09-30 12:30:10 에 등록된 네이버 페이 구매평)')
        text = build_copy_summary({'myeongga': [row]}, DAY, DAY, 'myeongga')['text']
        self.assertNotIn('010-1234', text)
        self.assertNotIn('person@', text)
        self.assertNotIn('등록된', text)


class CopySummaryApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_rows_no_store_and_read_only(self):
        import main
        cache = {'myeongga': [review() for _ in range(601)], 'raw_last_updated': 'test'}
        with patch.object(main, '_load_reviews_cached', return_value=cache), \
             patch.object(main, 'run_collect') as collect, \
             patch.object(main, 'run_daily_report') as archive:
            response = await main.get_review_copy_summary(DAY, DAY, 'myeongga')
        data = json.loads(response.body)
        self.assertEqual(data['total_count'], 601)
        self.assertEqual(data['source_updated_at'], 'test')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        collect.assert_not_called()
        archive.assert_not_called()

    async def test_invalid_or_unavailable_cache(self):
        import main
        for start, end, brand in [(None, DAY, 'all'), ('bad', DAY, 'all'), (DAY, DAY, 'bad')]:
            with patch.object(main, '_load_reviews_cached') as loader:
                with self.assertRaises(main.HTTPException) as error:
                    await main.get_review_copy_summary(start, end, brand)
                self.assertEqual(error.exception.status_code, 400)
                loader.assert_not_called()
        with patch.object(main, '_load_reviews_cached', return_value=None):
            with self.assertRaises(main.HTTPException) as error:
                await main.get_review_copy_summary(DAY, DAY)
            self.assertEqual(error.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
