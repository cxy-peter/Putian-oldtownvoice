import asyncio
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from aiohttp import web
from cloud_app import create_cloud_app, origins, signing_key, make_token, valid_token, COOKIE
from store import SEED

CODE='cloud-test-code-32-chars-not-production'
ORIGIN='https://putian-test.vercel.app'
ENV={'APP_ACCESS_CODE':CODE,'VERCEL':'1','VERCEL_URL':'putian-test.vercel.app','DASHSCOPE_API_KEY':'test-placeholder-not-a-real-key'}

class Security(unittest.TestCase):
    def setUp(self):
        self.app=create_cloud_app(ENV);self.client=TestClient(self.app,base_url=ORIGIN)
    def tearDown(self):self.client.close()
    def login(self):return self.client.post('/api/login',headers={'origin':ORIGIN},json={'code':CODE})
    def test_status_honest(self):
        r=self.client.get('/api/status');self.assertEqual(r.status_code,200);self.assertFalse(r.json()['liveVerified']);self.assertEqual(r.json()['storageMode'],'browser');self.assertNotIn(CODE,r.text)
    def test_origin_rejected(self):self.assertEqual(self.client.post('/api/login',json={'code':CODE},headers={'origin':'https://evil.invalid'}).status_code,403)
    def test_no_origin_rejected(self):self.assertEqual(self.client.post('/api/login',json={'code':CODE}).status_code,403)
    def test_wrong_code(self):self.assertEqual(self.client.post('/api/login',headers={'origin':ORIGIN},json={'code':'wrong'}).status_code,401)
    def test_cookie_flags(self):
        c=self.login().headers['set-cookie'];self.assertIn('HttpOnly',c);self.assertIn('Secure',c);self.assertIn('SameSite=strict',c)
    def test_auth(self):self.login();self.assertTrue(self.client.get('/api/status').json()['authenticated'])
    def test_other_instance_accepts_token(self):
        self.login();other=TestClient(create_cloud_app(ENV),base_url=ORIGIN);other.cookies.update(self.client.cookies);self.assertTrue(other.get('/api/status').json()['authenticated']);other.close()
    def test_tampered_token(self):
        self.login();token=self.client.cookies.get(COOKIE);self.assertFalse(valid_token(token+'x',signing_key(ENV)))
    def test_expired(self):self.assertFalse(valid_token(make_token(signing_key(ENV),1),signing_key(ENV),43202))
    def test_access_rotation_invalidates(self):self.assertFalse(valid_token(make_token(signing_key(ENV)),signing_key({**ENV,'APP_ACCESS_CODE':CODE+'new'})))
    def test_cloud_no_localhost(self):self.assertNotIn('http://localhost:8787',origins(ENV))
    def test_cloudflare_exact_origin(self):self.assertIn('https://voice.example.com',origins({**ENV,'ALLOWED_ORIGINS':'https://voice.example.com'}))
    def test_no_wildcards(self):
        with self.assertRaises(ValueError):origins({**ENV,'ALLOWED_ORIGINS':'https://*.example.com'})
    def test_auth_for_validate(self):self.assertEqual(self.client.post('/api/validate-corpus',headers={'origin':ORIGIN},json=SEED).status_code,401)
    def test_validate_terms(self):self.login();r=self.client.post('/api/validate-corpus',headers={'origin':ORIGIN},json=SEED);self.assertEqual(r.status_code,200)
    def test_validate_rejects_bad_weight(self):
        self.login();r=self.client.post('/api/validate-corpus',headers={'origin':ORIGIN},json={'terms':[{'text':'莆田','weight':99}]});self.assertEqual(r.status_code,400)
    def test_body_size(self):self.assertEqual(self.client.post('/api/login',headers={'origin':ORIGIN},content='x'*2100).status_code,400)
    def test_private_files_not_served(self):self.assertEqual(self.client.get('/.env').status_code,404);self.assertEqual(self.client.get('/cloud_app.py').status_code,404)
    def test_static(self):self.assertEqual(self.client.get('/local-store.js').status_code,200)
    def test_logout(self):self.login();self.client.post('/api/logout',headers={'origin':ORIGIN},json={});self.assertFalse(self.client.get('/api/status').json()['authenticated'])
    def test_missing_key_fails(self):
        other=TestClient(create_cloud_app({**ENV,'DASHSCOPE_API_KEY':''}),base_url=ORIGIN);other.post('/api/login',headers={'origin':ORIGIN},json={'code':CODE});r=other.post('/api/translate',headers={'origin':ORIGIN},json={'text':'测试','target':'zh'});self.assertEqual(r.status_code,503);other.close()
    def test_ws_rejects_unauth(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('wss://putian-test.vercel.app/ws',headers={'origin':ORIGIN}):pass
    def test_weak_access_fails(self):
        with self.assertRaises(ValueError):create_cloud_app({'APP_ACCESS_CODE':'weak'})
    def test_security_headers(self):self.assertEqual(self.client.get('/').headers['cache-control'],'no-store')

class Streaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop=asyncio.new_event_loop();cls.thread=threading.Thread(target=cls.loop.run_forever,daemon=True);cls.thread.start()
        async def setup():
            async def stream(request):
                ws=web.WebSocketResponse();await ws.prepare(request)
                first=await ws.receive_json();cls.first=first
                await ws.send_json({'header':{'event':'task-started'}})
                async for msg in ws:
                    if msg.type==web.WSMsgType.BINARY:
                        await ws.send_json({'header':{'event':'result-generated'},'payload':{'output':{'sentence':{'sentence_id':0,'text':'草稿测试','sentence_end':False}}}})
                    elif msg.type==web.WSMsgType.TEXT:
                        await ws.send_json({'header':{'event':'result-generated'},'payload':{'output':{'sentence':{'sentence_id':0,'text':'最终测试文字','sentence_end':True}}}})
                        await ws.send_json({'header':{'event':'task-finished'}});break
                return ws
            app=web.Application();app.router.add_get('/ws',stream);cls.runner=web.AppRunner(app);await cls.runner.setup();site=web.TCPSite(cls.runner,'127.0.0.1',0);await site.start();return site._server.sockets[0].getsockname()[1]
        cls.port=asyncio.run_coroutine_threadsafe(setup(),cls.loop).result()
    @classmethod
    def tearDownClass(cls):
        asyncio.run_coroutine_threadsafe(cls.runner.cleanup(),cls.loop).result();cls.loop.call_soon_threadsafe(cls.loop.stop);cls.thread.join();cls.loop.close()
    def test_final_is_drained_after_stop(self):
        app=create_cloud_app(ENV);app.state.upstream_urls=(f'ws://127.0.0.1:{self.port}/ws','','')
        with TestClient(app,base_url=ORIGIN) as client:
            client.post('/api/login',headers={'origin':ORIGIN},json={'code':CODE})
            with client.websocket_connect('wss://putian-test.vercel.app/ws',headers={'origin':ORIGIN}) as ws:
                ws.send_json({'type':'start','consent':True,'engine':'qwen31','corpus':SEED,'corpusRevision':7})
                self.assertEqual(ws.receive_json()['type'],'ready');ws.send_bytes(b'\0\0'*1600)
                self.assertFalse(ws.receive_json()['final']);ws.send_json({'type':'stop'})
                self.assertTrue(ws.receive_json()['final']);self.assertEqual(ws.receive_json()['type'],'done')
                self.assertIn('妈祖',self.first['payload']['parameters']['vocabulary'])

if __name__=='__main__':unittest.main()
