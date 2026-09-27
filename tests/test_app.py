import asyncio
import base64
import io
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web, CookieJar
from aiohttp.test_utils import TestClient, TestServer
from app import create_app
from engine import Protocol, endpoints, translation_body, validate_corpus
from store import Store, SEED, inspect_wav
from scripts.evaluate import evaluate

CODE="test-access-code-for-local-only"
ORIGIN="http://localhost:8787"
def audio(value=100):
    out=io.BytesIO()
    with wave.open(out,"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(value.to_bytes(2,"little",signed=True)*8000)
    return out.getvalue()
def sample(**kw):
    return {"audio":base64.b64encode(audio()).decode(),"reference":"测试文字","speaker":"s1","district":"莆田城区","split":"train","consent":True,"reviewed":True,**kw}

class ProtocolTests(unittest.TestCase):
    def test_new_hotwords(self):
        r=Protocol("qwen31",SEED).start();self.assertTrue(r["payload"]["parameters"]["keep_dialect"]);self.assertIn("妈祖",r["payload"]["parameters"]["vocabulary"])
    def test_qwen3_no_unsupported_options(self):
        r=Protocol("qwen3",SEED).start();self.assertNotIn("vocabulary",json.dumps(r));self.assertEqual(r["session"]["sample_rate"],16000)
    def test_funasr_no_immediate_hotwords(self):
        r=Protocol("funasr",SEED).start();self.assertNotIn("vocabulary",r["payload"]["parameters"]);self.assertIn("context",r["payload"]["input"])
    def test_baseline(self):
        r=Protocol("qwen31",SEED,enhance=False).start();self.assertEqual(r["payload"]["input"],{});self.assertNotIn("vocabulary",r["payload"]["parameters"])
    def test_qwen3_stash_replaced_not_appended(self):
        e=Protocol("qwen3",SEED).event({"type":"conversation.item.input_audio_transcription.text","text":"今天","stash":"回家","item_id":"i"});self.assertEqual(e["text"],"今天回家")
    def test_qwen3_final(self):
        e=Protocol("qwen3",SEED).event({"type":"conversation.item.input_audio_transcription.completed","transcript":"完整句子","item_id":"i"});self.assertTrue(e["final"])
    def test_sentence_events(self):
        p=Protocol("qwen31",SEED);self.assertIsNone(p.event({"header":{"event":"result-generated"},"payload":{"output":{"sentence":{"heartbeat":True}}}}))
    def test_error_does_not_leak(self):
        e=Protocol("qwen3",SEED).event({"type":"error","error":{"code":"BAD","message":"secret-key-text"}});self.assertNotIn("secret-key-text",json.dumps(e))
    def test_finish_protocol(self):
        self.assertEqual(Protocol("qwen3",SEED).finish()["type"],"session.finish");self.assertEqual(Protocol("qwen31",SEED).finish()["header"]["action"],"finish-task")
    def test_bad_engine(self):
        with self.assertRaises(ValueError):Protocol("unlisted",SEED)
    def test_endpoint_locked(self):
        with self.assertRaises(ValueError):endpoints("evil.com/path")
    def test_text_translation_not_global_replace(self):
        r=translation_body("妈祖在哪里？","zh",SEED);self.assertIn("transcript",r["messages"][1]["content"])
    def test_bad_target(self):
        with self.assertRaises(ValueError):translation_body("test","xx",SEED)
    def test_hotword_range(self):
        for w in (0,6,51,True,"3"):
            with self.assertRaises(ValueError):validate_corpus({"terms":[{"text":"a","weight":w}]})
    def test_duplicate_terms(self):
        with self.assertRaises(ValueError):validate_corpus({"terms":[{"text":"a"},{"text":"a"}]})
    def test_superword_limit(self):
        with self.assertRaises(ValueError):validate_corpus({"terms":[{"text":str(i),"weight":50} for i in range(51)]})
    def test_key_rejected(self):
        with self.assertRaises(ValueError):validate_corpus({"terms":[{"text":"sk-abcdefghijklmnop"}]})
    def test_unreviewed_example(self):
        with self.assertRaises(ValueError):validate_corpus({"examples":[{"source":"a","target":"b"}]})
    def test_no_data_no_accuracy(self):
        self.assertIsNone(evaluate([])["cer"])
    def test_cer_from_raw(self):
        self.assertEqual(evaluate([{"speaker":"s1","split":"test","reference":"你好","hypothesis":"你号"}])["cer"],.5)

class StorageTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def test_version_conflict(self):
        c=self.store.corpus();self.store.save_corpus(c)
        with self.assertRaises(ValueError):self.store.save_corpus(c)
    def test_persistence(self):
        c=self.store.corpus();c["terms"].append({"text":"新词","weight":2});self.store.save_corpus(c);self.store.close();self.store=Store(self.temp.name);self.assertEqual(self.store.corpus()["revision"],2)
    def test_audio_format(self):self.assertEqual(inspect_wav(audio()),.5)
    def test_invalid_audio(self):
        with self.assertRaises(ValueError):inspect_wav(b"not-a-wav")
    def test_requires_consent(self):
        with self.assertRaises(ValueError):self.store.add_sample(sample(consent=False))
    def test_requires_review(self):
        with self.assertRaises(ValueError):self.store.add_sample(sample(reviewed=False))
    def test_prevent_speaker_leakage(self):
        self.store.add_sample(sample())
        with self.assertRaises(ValueError):self.store.add_sample(sample(split="test",audio=base64.b64encode(audio(200)).decode()))
    def test_prevent_duplicate_audio(self):
        self.store.add_sample(sample())
        with self.assertRaises(ValueError):self.store.add_sample(sample(speaker="s2"))
    def test_export_private_only(self):
        self.store.add_sample(sample());z=zipfile.ZipFile(io.BytesIO(self.store.export()));self.assertEqual(len(z.namelist()),4);self.assertNotIn(".env",z.namelist())
    def test_delete(self):
        s=self.store.add_sample(sample());self.store.remove_sample(s["id"]);self.assertEqual(self.store.samples(),[])
    def test_daily_cap(self):
        self.store.reserve(2,3)
        with self.assertRaises(ValueError):self.store.reserve(2,3)

class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=create_app({"APP_ACCESS_CODE":CODE,"DATA_DIR":self.temp.name});self.client=TestClient(TestServer(self.app),cookie_jar=CookieJar(unsafe=True));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close();self.temp.cleanup()
    async def auth(self):
        return await self.client.post('/api/login',json={"code":CODE},headers={"Origin":ORIGIN})
    async def test_status_no_secret(self):
        r=await self.client.get('/api/status');data=await r.json();self.assertFalse(data["dialectValidated"]);self.assertNotIn(CODE,json.dumps(data))
    async def test_auth_required(self):self.assertEqual((await self.client.get('/api/corpus')).status,401)
    async def test_bad_origin(self):self.assertEqual((await self.client.post('/api/login',json={"code":CODE},headers={"Origin":"https://evil.invalid"})).status,403)
    async def test_cookie_httponly(self):r=await self.auth();self.assertIn('HttpOnly',r.headers['Set-Cookie'])
    async def test_login_and_corpus(self):await self.auth();self.assertEqual((await self.client.get('/api/corpus')).status,200)
    async def test_missing_key(self):await self.auth();r=await self.client.post('/api/translate',json={"text":"test","target":"zh"},headers={"Origin":ORIGIN});self.assertEqual(r.status,503)
    async def test_env_not_public(self):self.assertEqual((await self.client.get('/.env')).status,404)
    async def test_csp(self):r=await self.client.get('/');self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
    async def test_logout_revokes(self):await self.auth();await self.client.post('/api/logout',json={},headers={"Origin":ORIGIN});self.assertEqual((await self.client.get('/api/samples')).status,401)
    async def test_ws_auth(self):
        r=await self.client.get('/ws',headers={"Origin":ORIGIN});self.assertEqual(r.status,401)
    async def test_stream_final_tail(self):
        seen=[]
        async def mock(request):
            sock=web.WebSocketResponse();await sock.prepare(request);start=await sock.receive_json();seen.append(start)
            await sock.send_json({"header":{"event":"task-started"}})
            async for msg in sock:
                if msg.type==web.WSMsgType.BINARY:
                    seen.append(len(msg.data));await sock.send_json({"header":{"event":"result-generated"},"payload":{"output":{"sentence":{"sentence_id":1,"text":"测试","sentence_end":False}}}})
                elif msg.type==web.WSMsgType.TEXT:
                    seen.append(json.loads(msg.data));await sock.send_json({"header":{"event":"result-generated"},"payload":{"output":{"sentence":{"sentence_id":1,"text":"测试句尾。","sentence_end":True}}}});await sock.send_json({"header":{"event":"task-finished"}});break
            await sock.close();return sock
        upstream=web.Application();upstream.router.add_get('/mock',mock);srv=TestServer(upstream);await srv.start_server()
        self.app['key']='local-test-placeholder';self.app['endpoints']=(str(srv.make_url('/mock')).replace('http:','ws:'),"unused","unused")
        try:
            await self.auth();sock=await self.client.ws_connect('/ws',headers={"Origin":ORIGIN});await sock.send_json({"type":"start","engine":"qwen31","consent":True});self.assertEqual((await sock.receive_json())["type"],"ready")
            await sock.send_bytes(b'\x01\x00'*1600);self.assertFalse((await sock.receive_json())["final"]);await sock.send_json({"type":"stop"});last=await sock.receive_json();self.assertEqual(last["text"],"测试句尾。");self.assertTrue(last["final"]);self.assertEqual((await sock.receive_json())["type"],"done");await sock.close();await asyncio.sleep(.05);self.assertEqual(self.app['active'],0);self.assertEqual(seen[-1]['header']['action'],'finish-task')
        finally:await srv.close()

if __name__=='__main__':unittest.main()
