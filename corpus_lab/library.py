"""Local reference corpus. Text entries are never counted as recorded speech.
Third-party metadata stays unreviewed. No URL in an import is fetched by this module.
"""
from __future__ import annotations
import base64, datetime as dt, hashlib, io, json, math, re, sqlite3, uuid, wave, zipfile
from pathlib import Path
from urllib.parse import urlsplit
from .normalise_edialect import normalize, rows, identifier, string, mandarin_values

HERE = Path(__file__).resolve().parent
ALIASES = {'飯':['饭'], '食飯':['食饭','吃饭'], '莆田':['莆田'], '莆田話':['莆田话'], '莆仙話':['莆仙话']}

def clean(value, limit=2000, required=False):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value:
        raise ValueError('字段类型或长度不正确。')
    value=value.strip()
    if required and not value: raise ValueError('请填写必填字段。')
    if re.search(r'sk-[A-Za-z0-9_-]{16,}',value): raise ValueError('请勿在语料中填写 API Key。')
    return value

def public_url(value):
    value=clean(value,4096)
    if not value:return ''
    u=urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query:
        raise ValueError('来源链接须为不含凭据或查询参数的 HTTPS 地址。')
    return value

def norm(value):
    return re.sub(r'\s+','',value.casefold()).translate(str.maketrans('飯話華語','饭话华语'))

def audio_data(encoded):
    if not isinstance(encoded,str) or len(encoded)>1_500_000:
        raise ValueError('音频过大，请使用 0.3–30 秒短句。')
    try:
        raw=base64.b64decode(encoded,validate=True)
        with wave.open(io.BytesIO(raw),'rb') as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getcomptype())!=(1,2,16000,'NONE'):
                raise ValueError('需要 16 kHz 单声道 PCM WAV；网页会自动转换。')
            n=w.getnframes(); pcm=w.readframes(n)
            if len(pcm)!=n*2 or not .3<=n/16000<=30:
                raise ValueError('录音须完整且为 0.3–30 秒。')
    except (wave.Error,EOFError,TypeError) as e:
        raise ValueError('音频不是完整 WAV。') from e
    import array,sys
    samples=array.array('h');samples.frombytes(pcm)
    if sys.byteorder!='little': samples.byteswap()
    rms=math.sqrt(sum(x*x for x in samples)/n)/32768
    if rms<.002: raise ValueError('录音音量过低或没有声音，请先回放后重新录制。')
    return raw,{'seconds':round(n/16000,3),'sha256':hashlib.sha256(pcm).hexdigest(),'rms':round(rms,5)}

class Library:
    def __init__(self,folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.folder/'library.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
        self.db.commit();self.seed()

    def seed(self):
        with self.db:
            for line in (HERE/'seed.jsonl').read_text(encoding='utf-8').splitlines():
                r=json.loads(line)
                value={'id':r['id'],'word':r['word'],'pinyin':r['pinyin_raw'],'ipa':'',
                    'mandarin':[],'aliases':ALIASES.get(r['word'],[]),'district':r['dialect_scope_as_stated'],
                    'source_url':r['source'],'source_id':'hinghua_factory','source_blob':r['source_blob'],
                    'status':'reference_only','audio_url':'','audio_kind':'none','reviewed':False,
                    'rights_note':'仓库采用 MPL-2.0；完整上游数据范围尚未核实。' ,'note':'公开字词编码摘例；别名仅辅助检索，不是已核对的音义答案。'}
                self.db.execute('INSERT OR IGNORE INTO entries VALUES (?,?)',(r['id'],json.dumps(value,ensure_ascii=False)))

    def entries(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM entries ORDER BY rowid')]

    def samples(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM samples ORDER BY rowid DESC')]

    def entry(self,ident):
        if not isinstance(ident,str): raise ValueError('词条 ID 无效。')
        r=self.db.execute('SELECT body FROM entries WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('未找到这个词条。')
        return json.loads(r[0])

    def sample(self,ident):
        if not isinstance(ident,str): raise ValueError('录音 ID 无效。')
        r=self.db.execute('SELECT body FROM samples WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('未找到这个录音。')
        return json.loads(r[0])

    def stats(self):
        entries=self.entries();samples=self.samples()
        return {'entries':len(entries),'bundled_references':sum(x['source_id']=='hinghua_factory' for x in entries),
            'external_audio_links':sum(bool(x.get('audio_url')) for x in entries),
            'local_audio':len(samples),'reference_audio':sum(x['allow_reference'] and x['split'] not in ('dev','test') for x in samples),
            'training_authorized_audio':sum(x['training_allowed'] and x['split']=='train' for x in samples),
            'fine_tuned':False,'downloaded_external_audio':0}

    def search(self,q='',limit=80):
        q=norm(clean(q,160)); found=[]
        for e in self.entries():
            parts=[e['word'],e['pinyin'],e.get('ipa',''),*e.get('aliases',[]),*e.get('mandarin',[])]
            if not q or any(q in norm(x) for x in parts):found.append(e)
        found.sort(key=lambda e: (norm(e['word'])!=q,len(e['word'])))
        return found[:limit],len(found)

    def import_data(self,obj):
        if not isinstance(obj,dict) or obj.get('consent_process') is not True:
            raise ValueError('导入前须确认有权处理这些本地材料。')
        kind=obj.get('kind'); items=[];quarantine=[]
        label=clean(obj.get('source_name','本地授权导入'),120,True)
        base=public_url(obj.get('source_base',''))
        if kind=='edialect':
            if not base: raise ValueError('请填写经确认的 e-dialect 来源地址。')
            wr=rows(obj.get('words'),'words');pr=rows(obj.get('pronunciations',[]),'pronunciations')
            if len(wr)>500 or len(pr)>1000: raise ValueError('每批最多 500 词条、1000 发音元数据。')
            candidates,quarantine,_=normalize(wr,pr,base)
            namespace=hashlib.sha256(base.encode()).hexdigest()[:12]
            for w in wr:
                if w.get('visibility') is False: continue
                wid=identifier(w.get('id'))
                items.append({'id':f'ed-{namespace}-w-{wid}','word':string(w.get('word'),1000),
                   'pinyin':string(w.get('standard_pinyin'),1000),'ipa':string(w.get('standard_ipa'),1000),
                   'mandarin':mandarin_values(w.get('mandarin')),'aliases':[],'district':'地区待确认',
                   'source_url':f'{base.rstrip("/")}/words/{wid}','source_id':label,
                   'status':'pending_review','audio_url':'','audio_kind':'unknown','reviewed':False,
                   'rights_note':'仅按用户许可导入；未取得训练或再分发授权。','note':'词条顶层 source 未用作录音标签。'})
            for c in candidates:
                if urlsplit(c['audio_source']).scheme!='https':
                    quarantine.append({'reason':'http_audio_not_imported'});continue
                items.append({'id':f'ed-{namespace}-p-{c["pronunciation_id"]}', 'word':c['word'],
                    'pinyin':c['pinyin'],'ipa':c['ipa'],'mandarin':c['mandarin_candidates'],'aliases':[],
                    'district':' / '.join(x for x in [c['county'],c['town']] if x) or '地区待确认',
                    'source_url':c['source_page'],'source_id':label,'status':'pending_review',
                    'audio_url':public_url(c['audio_source']), 'audio_kind':'unknown','reviewed':False,
                    'word_id':c['word_id'],'pronunciation_id':c['pronunciation_id'],
                    'rights_note':'未确认录音授权；不会自动下载。', 'note':'按 word_id 明确关联；贡献者不当作说话人。'})
        elif kind=='manual':
            records=obj.get('records')
            if not isinstance(records,list) or not 1<=len(records)<=500: raise ValueError('每批请提供 1–500 条 JSON/JSONL 记录。')
            for i,r in enumerate(records):
                if not isinstance(r,dict):raise ValueError('每条记录须为 JSON 对象。')
                word=clean(r.get('word',''),200,True);pinyin=clean(r.get('pinyin',r.get('pinyin_raw','')),300)
                url=public_url(r.get('source_url',r.get('source_page',r.get('source',base))))
                # Import deliberately strips claimed approvals, local paths, user data and secrets.
                unique=json.dumps([label,url,word,pinyin,r.get('ipa','')],ensure_ascii=False)
                items.append({'id':'manual-'+hashlib.sha256(unique.encode()).hexdigest()[:24],
                    'word':word,'pinyin':pinyin,'ipa':clean(r.get('ipa',''),300),
                    'mandarin':mandarin_values(r.get('mandarin',r.get('mandarin_candidates',[]))),
                    'aliases':[],'district':clean(r.get('district',r.get('county','地区待确认')),160),
                    'source_url':url,'source_id':label,'status':'pending_review','reviewed':False,
                    'audio_url':public_url(r.get('audio_url',r.get('audio_source','')) or ''),'audio_kind':'unknown',
                    'rights_note':'导入不等于审核或训练授权。','note':clean(r.get('note',''),800)})
        else:raise ValueError('请选择 e-dialect 导出或手动 JSON/JSONL 格式。')
        if len(self.entries())+len(items)>5000:
            raise ValueError("工作台最多 5000 条元数据，请分库管理。")
        created=0
        with self.db:
            for item in items:
                cur=self.db.execute('INSERT OR IGNORE INTO entries VALUES (?,?)',(item['id'],json.dumps(item,ensure_ascii=False)))
                created+=cur.rowcount
            audit={'time':dt.datetime.now(dt.timezone.utc).isoformat(),'source':label,'imported':created,
                'duplicates_skipped':len(items)-created,'quarantined':len(quarantine),'audio_downloaded':0}
            self.db.execute('INSERT INTO events(body) VALUES (?)',(json.dumps(audit,ensure_ascii=False),))
        return audit

    def add_audio(self,obj):
        if not isinstance(obj,dict) or not all(obj.get(x) is True for x in ('reviewed','consent_store','human_confirmed')):
            raise ValueError('须确认真人录音、母语者核对以及本地保存许可。')
        if len(self.samples())>=200: raise ValueError("本机工作台最多 200 条录音，请先导出整理。")
        audio,info=audio_data(obj.get('audio'))
        entry_id=obj.get('entry_id') or None
        if entry_id:self.entry(entry_id)
        speaker=clean(obj.get('speaker',''),64,True)
        reviewer=clean(obj.get('reviewer',''),64,True)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',speaker) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',reviewer):
            raise ValueError('请使用 P001 / R001 这样的匿名编号。')
        split=obj.get('split','unassigned')
        if split not in ('unassigned','train','dev','test'):raise ValueError('数据划分不正确。')
        for r in self.samples():
            if r['audio']['sha256']==info['sha256']:raise ValueError('同一音频已保存，不重复导入。')
            if r['speaker_id']==speaker and split!='unassigned' and r['split']!='unassigned' and r['split']!=split:
                raise ValueError('同一说话人不能跨 train/dev/test。')
        ident=uuid.uuid4().hex
        record={'id':ident,'entry_id':entry_id,'mandarin':clean(obj.get('mandarin',''),1000,True),
            'speaker_id':speaker,'reviewer_id':reviewer,'district':clean(obj.get('district',''),160,True),
            'split':split,'reviewed':True,'human_confirmed':True,'consent_store':True,
            'allow_reference':obj.get('allow_reference') is True,
            'training_allowed':obj.get('training_allowed') is True,'audio':info,'audio_path':f'audio/{ident}.wav',
            'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'note':'真人/含义为用户确认，非系统独立鉴定。未训练模型；无公开再分发授权。'}
        p=self.folder/record['audio_path'];p.parent.mkdir(exist_ok=True);p.write_bytes(audio)
        try:
            with self.db:self.db.execute('INSERT INTO samples VALUES(?,?,?)',(ident,info['sha256'],json.dumps(record,ensure_ascii=False)))
        except Exception:p.unlink(missing_ok=True);raise
        return record

    def reserve_call(self,limit=60):
        day=dt.datetime.now(dt.timezone.utc).date().isoformat()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO budget VALUES(?,0)',(day,))
            if self.db.execute('SELECT calls FROM budget WHERE day=?',(day,)).fetchone()[0]>=limit:
                raise ValueError('工作台已达每日 60 次云调用保护上限。')
            self.db.execute('UPDATE budget SET calls=calls+1 WHERE day=?',(day,))

    def export(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('entries.json',json.dumps(self.entries(),ensure_ascii=False,indent=2))
            z.writestr('manifest.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in self.samples()))
            z.writestr('README.txt','私有备份：含用户录音，不要上传公开 GitHub。词条与录音数量分别统计。导出不是训练或再分发授权。\n')
            for r in self.samples():z.write(self.folder/r['audio_path'],r['audio_path'])
        return out.getvalue()
