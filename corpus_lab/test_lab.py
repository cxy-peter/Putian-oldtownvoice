import asyncio,base64,hashlib,io,json,math,os,struct,sys,tempfile,unittest,wave,zipfile
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from .library import Library,audio_data,public_url
from .routes import request_body
from .acoustic import retrieve

def wav(freq=170,seconds=.6):
    o=io.BytesIO()
    with wave.open(o,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'))
        w.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*freq*i/16000))) for i in range(int(seconds*16000))))
    return o.getvalue()
def pair(freq=170,**kw):
    return {'audio':base64.b64encode(wav(freq)).decode(),'speaker':'P001','reviewer':'R001','district':'合成测试音：不是莆仙话',
        'mandarin':'合成音测试标签（非真实词义）','split':'train','consent_store':True,'human_confirmed':True,
        'reviewed':True,'allow_reference':True,**kw}
def imp(**kw):
    return {'kind':'manual','source_name':'unit-test','source_base':'https://example.org',
        'consent_process':True,'records':[{'word':'测试词条','pinyin':'abc1','mandarin':['仅测试'],'source_url':'https://example.org/test'}],**kw}

class DataTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.lib=Library(self.t.name)
    def tearDown(self):self.lib.db.close();self.t.cleanup()
    def test_seed_counts(self):self.assertEqual(self.lib.stats()['entries'],5);self.assertEqual(self.lib.stats()['local_audio'],0)
    def test_seed_idempotent(self):self.lib.seed();self.assertEqual(len(self.lib.entries()),5)
    def test_mandarin_alias(self):self.assertEqual(self.lib.search('吃饭')[0][0]['word'],'食飯')
    def test_simplified(self):self.assertEqual(self.lib.search('莆田话')[0][0]['word'],'莆田話')
    def test_romanization(self):self.assertEqual(self.lib.search('sia2 mue5')[0][0]['word'],'食飯')
    def test_no_false_asr(self):self.assertEqual(self.lib.search('黑脸阿妈')[1],0)
    def test_no_invented_phonetics(self):self.assertEqual(self.lib.search('kliyama')[1],0)
    def test_no_seed_labels(self):self.assertFalse(any(r['reviewed'] or r['mandarin'] for r in self.lib.entries()))
    def test_manual_import(self):a=self.lib.import_data(imp());self.assertEqual(a['imported'],1)
    def test_import_idempotent(self):self.lib.import_data(imp());self.assertEqual(self.lib.import_data(imp())['duplicates_skipped'],1)
    def test_import_consent(self):
        with self.assertRaises(ValueError):self.lib.import_data(imp(consent_process=False))
    def test_import_cannot_claim_review(self):
        self.lib.import_data(imp(records=[{'word':'A','reviewed':True,'training_ready':True}]))
        self.assertFalse(self.lib.search('A')[0][0]['reviewed'])
    def test_import_cannot_add_audio_count(self):
        self.lib.import_data(imp(records=[{'word':'A','audio_url':'https://example.org/a.wav'}]));self.assertEqual(self.lib.stats()['local_audio'],0)
    def test_no_credentials_in_url(self):
        with self.assertRaises(ValueError):public_url('https://u:pass@example.org')
    def test_no_query_credentials(self):
        with self.assertRaises(ValueError):public_url('https://example.org/?token=secret')
    def test_import_unknown_id(self):
        words=[{'id':1,'word':'A','source':'https://example.org/wrong.wav'}]
        pro=[{'id':2,'word_id':99,'visibility':True,'source':'https://example.org/a.wav'}]
        a=self.lib.import_data(imp(kind='edialect',words=words,pronunciations=pro))
        self.assertEqual(a['quarantined'],1);self.assertEqual(self.lib.stats()['external_audio_links'],0)
    def test_explicit_join(self):
        words=[{'id':1,'word':'A','mandarin':['M'],'source':'https://example.org/wrong.wav'}]
        pro=[{'id':2,'word_id':1,'visibility':True,'source':'https://example.org/right.wav'}]
        self.lib.import_data(imp(kind='edialect',words=words,pronunciations=pro))
        es=[x for x in self.lib.entries() if x.get('audio_url')];self.assertEqual(len(es),1);self.assertIn('/right.wav',es[0]['audio_url'])
    def test_nonpublic_audio_excluded(self):
        a=self.lib.import_data(imp(kind='edialect',words=[{'id':1,'word':'A'}],pronunciations=[{'id':2,'word_id':1,'visibility':False,'source':'https://example.org/a.wav'}]))
        self.assertEqual(a['quarantined'],1)
    def test_import_no_personal_fields(self):
        self.lib.import_data(imp(records=[{'word':'A','contributor':{'email':'private@example.org'}}]))
        self.assertNotIn('private@example',json.dumps(self.lib.entries()))
    def test_wav(self):self.assertAlmostEqual(audio_data(base64.b64encode(wav()).decode())[1]['seconds'],.6)
    def test_wav_silence(self):
        with self.assertRaises(ValueError):audio_data(base64.b64encode(wav(0)).decode())
    def test_wav_invalid(self):
        with self.assertRaises(ValueError):audio_data('!!!')
    def test_save_record(self):self.lib.add_audio(pair());self.assertEqual(self.lib.stats()['local_audio'],1)
    def test_save_permissions_required(self):
        for field in ('human_confirmed','reviewed','consent_store'):
            with self.assertRaises(ValueError):self.lib.add_audio(pair(**{field:False}))
    def test_unknown_entry(self):
        with self.assertRaises(ValueError):self.lib.add_audio(pair(entry_id='missing'))
    def test_audio_dedup(self):
        self.lib.add_audio(pair())
        with self.assertRaises(ValueError):self.lib.add_audio(pair())
    def test_speaker_split(self):
        self.lib.add_audio(pair())
        with self.assertRaises(ValueError):self.lib.add_audio(pair(200,split='test'))
    def test_no_auto_training(self):self.lib.add_audio(pair());self.assertFalse(self.lib.stats()['fine_tuned']);self.assertEqual(self.lib.stats()['training_authorized_audio'],0)
    def test_training_explicit(self):self.lib.add_audio(pair(training_allowed=True));self.assertEqual(self.lib.stats()['training_authorized_audio'],1)
    def test_dev_never_reference(self):self.lib.add_audio(pair(split='dev'));self.assertEqual(self.lib.stats()['reference_audio'],0)
    def test_export(self):
        self.lib.add_audio(pair());z=zipfile.ZipFile(io.BytesIO(self.lib.export()));self.assertIn('manifest.jsonl',z.namelist());self.assertEqual(sum(n.endswith('.wav') for n in z.namelist()),1)
    def test_budget(self):
        self.lib.reserve_call(1)
        with self.assertRaises(ValueError):self.lib.reserve_call(1)
    def test_direct_prompt_not_labels(self):
        b=request_body(wav(),'qwen3-omni-flash');p=b['messages'][0]['content'][1]['text'];self.assertNotIn('吃饭',p);self.assertNotIn('黑脸',p)
    def test_invalid_model(self):
        with self.assertRaises(ValueError):request_body(wav(),'untrusted')
    def test_reference_is_marked(self):b=request_body(wav(),'qwen3-omni-flash',[{'mandarin':'LABEL'}]);self.assertIn('不是当前答案',json.dumps(b,ensure_ascii=False))
    def test_retrieve_excludes_identical(self):
        self.lib.add_audio(pair());raw,info=audio_data(pair()['audio']);r=retrieve(raw,info,self.lib.samples(),self.lib.folder);self.assertEqual(r['matches'],[]);self.assertEqual(r['identical_excluded'],1)
    def test_retrieval_candidates_only(self):
        self.lib.add_audio(pair());raw,info=audio_data(pair(181)['audio']);r=retrieve(raw,info,self.lib.samples(),self.lib.folder);self.assertEqual(len(r['matches']),1);self.assertFalse(r['calibrated']);self.assertEqual(r['matches'][0]['kind'],'candidate_not_translation')
    def test_test_sample_not_retrieved(self):
        self.lib.add_audio(pair(split='test'));raw,info=audio_data(pair(181)['audio']);r=retrieve(raw,info,self.lib.samples(),self.lib.folder);self.assertEqual(r['matches'],[])

class Routes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import app
        self.t=tempfile.TemporaryDirectory();self.app=app.create_app({'APP_ACCESS_CODE':'test-access-code-not-a-secret','DATA_DIR':self.t.name,'PORT':'8787'})
        self.client=TestClient(TestServer(self.app));await self.client.start_server();self.origin={'Origin':'http://localhost:8787'}
    async def asyncTearDown(self):await self.client.close();self.t.cleanup()
    async def login(self):
        self.app['sessions']['test-session']=__import__('time').monotonic()+60
        self.client.session.cookie_jar.update_cookies({'pv_session':'test-session'})
    async def test_static(self):r=await self.client.get('/corpus');self.assertEqual(r.status,200);self.assertIn('语料工作台',await r.text())
    async def test_protected(self):r=await self.client.get('/api/lab/status');self.assertEqual(r.status,401)
    async def test_authenticated_counts(self):
        await self.login();r=await self.client.get('/api/lab/status');self.assertEqual((await r.json())['stats']['entries'],5)
    async def test_bad_origin(self):
        await self.login();r=await self.client.post('/api/lab/import',json=imp(),headers={'Origin':'https://attacker.invalid'});self.assertEqual(r.status,403)
    async def test_import_route(self):
        await self.login();r=await self.client.post('/api/lab/import',json=imp(),headers=self.origin);self.assertEqual((await r.json())['imported'],1)
    async def test_audio_private(self):
        await self.login();r=await self.client.post('/api/lab/save',json=pair(),headers=self.origin);d=await r.json();self.assertEqual(r.status,200)
        x=await self.client.get('/api/lab/audio/'+d['sample']['id']);self.assertEqual(x.status,200);self.assertEqual(await x.read(),wav())
    async def test_missing_api_key_clear_error(self):
        await self.login();r=await self.client.post('/api/lab/infer',json={'audio':pair()['audio'],'consent_cloud':True},headers=self.origin);self.assertEqual(r.status,400)
    async def test_cloud_consent(self):
        await self.login();r=await self.client.post('/api/lab/infer',json={'audio':pair()['audio']},headers=self.origin);self.assertEqual(r.status,400)
    async def test_original_home_stays(self):r=await self.client.get('/');self.assertEqual(r.status,200)
    async def test_csp_no_inline(self):r=await self.client.get('/corpus');self.assertNotIn('unsafe-inline',r.headers['Content-Security-Policy'])
    async def test_cloudflare_origin(self):
        self.app['origin']='https://unit-test.trycloudflare.com';r=await self.client.post('/api/login',json={'code':'test-access-code-not-a-secret'},headers={'Origin':self.app['origin']});self.assertEqual(r.status,200);self.assertIn('Secure',r.headers['Set-Cookie'])

if __name__=='__main__':unittest.main()
