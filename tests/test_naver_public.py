import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import naver_public as public
import naver_automation as worker


class PublicTests(unittest.TestCase):
    def test_store_scope_ignores_other_stores_and_login_urls(self):
        self.assertEqual(public.product_link('/100yearshop/products/123?x=1')[0], '123')
        for url in ('https://brand.naver.com.evil/100yearshop/products/1',
                    'https://nid.naver.com/nidlogin.login', '/other/products/1', 'http://brand.naver.com/100yearshop/products/1'):
            self.assertIsNone(public.product_link(url))

    def test_review_identity_and_dates_are_required(self):
        row = {'reviewContent':'맛있어요', 'reviewScore':5, 'reviewId':99,
               'createDate':'2026-09-16T01:02:03+09:00', 'productNo':123, 'writerMemberId':'abcdef'}
        result = public.decode_reviews({'contents':[row]}, '123', '상품', 'url')
        self.assertEqual(result[0]['review_no'], '99')
        self.assertEqual(result[0]['author'], 'ab***')
        self.assertEqual(public.decode_reviews({'contents':[row]}, '999', '상품', 'url'), [])
        self.assertEqual(public.decode_reviews({'aggregateRating':5, 'totalCount':2}, '123', '상품', 'url'), [])
        row['createDate'] = 'unknown'
        with self.assertRaises(public.CollectionStopped):
            public.decode_reviews(row, '123', '상품', 'url')

    def test_retry_after_respected_and_has_one_day_floor(self):
        self.assertEqual(public.retry_deadline('60', 100), 86500)
        self.assertEqual(public.retry_deadline('172800', 100), 172900)
        self.assertEqual(public.retry_deadline('invalid', 100), 86500)

    def test_429_stops_after_one_request_without_a_browser(self):
        import httpx
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(429, headers={'Retry-After':'172800'}, request=request)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('httpx.AsyncClient', return_value=client):
            with self.assertRaises(public.CollectionStopped) as caught:
                asyncio.run(public.collect('2026-09-01'))
        self.assertEqual(caught.exception.state, 'blocked')
        self.assertEqual(len(requests), 1)
        self.assertNotIn('authorization', requests[0].headers)
        self.assertNotIn('cookie', requests[0].headers)

    def test_robots_disallow_stops_before_store(self):
        import httpx
        seen = []
        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, text='User-agent: *\nDisallow: /\n', request=request)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('httpx.AsyncClient', return_value=client):
            with self.assertRaises(public.CollectionStopped) as caught:
                asyncio.run(public.collect('2026-09-01'))
        self.assertEqual(caught.exception.state, 'not_allowed')
        self.assertEqual(seen, ['https://brand.naver.com/robots.txt'])


if __name__ == '__main__':
    unittest.main()
