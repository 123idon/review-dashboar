import copy,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import httpx
import daily_analysis as a
from daily_report import build_report

def report():
    return build_report({'jasaol':[dict(review_no='1',date='2026-09-16',score=5,content='떡이 굳어서 왔어요. 선물 주문을 취소했습니다.')],
                         'myeongga':[]},'2026-09-16')

def answer():
    return {'summary':'높은 별점에도 제품 상태 불만이 있습니다.', 'findings':[{
        'brand':'jasaol','title':'제품 상태 확인','meaning':'5점 후기에도 굳음이 언급됩니다.',
        'action':'해당 배송 및 출고 상태를 확인하세요.',
        'evidence':[{'review_id':'jasaol:0','quote':'떡이 굳어서 왔어요.'}]}]}

class AnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_persist_once_and_get_is_read_only(self):
        calls=[]
        def handler(req):
            calls.append(json.loads(req.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer())}}],
                                           'usage':{'prompt_tokens':200,'completion_tokens':100,'total_tokens':300}})
        real=httpx.AsyncClient
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAILY_ANALYSIS_ENABLED':'1','OPENAI_API_KEY':'test-secret'}),patch.object(a.httpx,'AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
            r=report(); clock=datetime(2026,9,17,0,5,tzinfo=timezone.utc)
            result=await a.generate(r,td,clock)
            self.assertEqual(result['status'],'ready')
            self.assertEqual((await a.generate(r,td,clock))['status'],'ready')
            self.assertEqual(a.read(td,r)['usage']['total_tokens'],300)
            changed=copy.deepcopy(r);changed['total']+=1
            self.assertEqual(a.read(td,changed)['status'],'stale')
            self.assertEqual((await a.generate(changed,td,clock))['status'],'stale')
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['model'],a.MODEL)
            self.assertEqual(calls[0]['max_completion_tokens'],2500)
            self.assertNotIn('test-secret',Path(td,'2026-09-16.json').read_text())

    async def test_failure_does_not_retry_or_leak_error(self):
        calls=[]
        def handler(req):calls.append(req);return httpx.Response(429,json={'error':'secret-provider-body'})
        real=httpx.AsyncClient
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAILY_ANALYSIS_ENABLED':'1','OPENAI_API_KEY':'test-secret'}),patch.object(a.httpx,'AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
            result=await a.generate(report(),td)
            self.assertEqual(result['status'],'error')
            await a.generate(report(),td)
            self.assertEqual(len(calls),1)
            self.assertNotIn('secret-provider-body',json.dumps(result))

    def test_grounding_and_brand_validation(self):
        rows=a.source(report())['reviews']
        self.assertEqual(len(a.validate(answer(),rows)['findings']),1)
        for brand,quote in [('myeongga','떡이 굳어서 왔어요.'),('jasaol','배송이 지연됐습니다.')]:
            bad=answer();bad['findings'][0]['brand']=brand;bad['findings'][0]['evidence'][0]['quote']=quote
            with self.assertRaises(ValueError):a.validate(bad,rows)

    async def test_disabled_and_oversize_do_not_call(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAILY_ANALYSIS_ENABLED':'0'}):
            self.assertEqual((await a.generate(report(),td))['status'],'unavailable')
            self.assertFalse((Path(td)/'runs').exists())
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAILY_ANALYSIS_ENABLED':'1','OPENAI_API_KEY':'test'}),patch.object(a,'MAX_INPUT_BYTES',10):
            self.assertEqual((await a.generate(report(),td))['status'],'limited')
            self.assertFalse((Path(td)/'runs').exists())

    def test_redact_contact_data(self):
        self.assertNotIn('010-1234-5678',a.scrub('연락 010-1234-5678 test@example.com'))
        self.assertNotIn('test@example.com',a.scrub('연락 010-1234-5678 test@example.com'))
