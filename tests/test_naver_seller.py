import hashlib
import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from naver_seller import authorize, ROW_JS
class SellerTests(unittest.TestCase):
 def test_railway_https_origin_allowed_but_foreign_origin_rejected(self):
  from fastapi import FastAPI
  from fastapi.testclient import TestClient
  from naver_seller import router
  app=FastAPI();app.include_router(router)
  env={'NAVER_SELLER_CONNECT_SHA256':hashlib.sha256(b'test-secret').hexdigest(),'NAVER_SELLER_CONNECT_EXPIRES':str(time.time()+30),'RAILWAY_PUBLIC_DOMAIN':'reviews.example.com'}
  with patch.dict('os.environ',env,clear=True),TestClient(app) as client:
   for origin,expected in [('https://reviews.example.com',200),('https://evil.example',403),('https://reviews.example.com.evil.example',403)]:
    r=client.post('/api/naver-seller/connect',json={'action':'close'},headers={'X-Naver-Connect':'test-secret','Origin':origin})
    self.assertEqual(r.status_code,expected)
 def test_console_disabled_without_explicit_secret_and_expiry(self):
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(HTTPException): authorize('anything')
 def test_console_token_and_expiry_both_required(self):
  env={'NAVER_SELLER_CONNECT_SHA256':hashlib.sha256(b'test-secret').hexdigest(),'NAVER_SELLER_CONNECT_EXPIRES':str(time.time()+30)}
  with patch.dict('os.environ',env,clear=True):
   authorize('test-secret')
   with self.assertRaises(HTTPException): authorize('wrong')
  env['NAVER_SELLER_CONNECT_EXPIRES']='1'
  with patch.dict('os.environ',env,clear=True):
   with self.assertRaises(HTTPException): authorize('test-secret')
 def test_dom_reader_uses_observed_identifiers_only(self):
  self.assertIn('openReviewDetailModal',ROW_JS)
  self.assertIn('querySelector',ROW_JS)
  self.assertNotIn('angular.element',ROW_JS)

 def test_disabled_console_endpoint_returns_no_image_or_credentials(self):
  from fastapi import FastAPI
  from fastapi.testclient import TestClient
  from naver_seller import router
  app=FastAPI();app.include_router(router)
  with patch.dict('os.environ',{},clear=True),TestClient(app) as client:
   for action in ('start','image','save','text'):
    r=client.post('/api/naver-seller/connect',json={'action':action})
    self.assertEqual(r.status_code,403)
