/* Browser-only private persistence for serverless deployments. Never stores API keys. */
'use strict';
window.PutianStorage = (() => {
  const enc = new TextEncoder();
  let connection;
  const copy = value => structuredClone(value);
  const cleanText = (v, limit, required=false) => {
    if (typeof v !== 'string' || v.length > limit || (required && !v.trim()) || /sk-[A-Za-z0-9_-]{12,}/.test(v)) throw Error('标注字段无效或包含密钥。');
    return v.trim();
  };
  async function open() {
    if (!window.indexedDB) throw Error('此浏览器不支持 IndexedDB，不能持久保存语料。');
    if (!connection) connection = new Promise((resolve, reject) => {
      const r = indexedDB.open('putian-private-v1', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('state');
      r.onerror = () => reject(Error('无法打开本地语料库；请检查隐私模式与存储权限。'));
      r.onblocked = () => reject(Error('存储升级被其他标签页阻止，请关闭旧页面。'));
      r.onsuccess = () => {r.result.onversionchange = () => {r.result.close(); connection = null;}; resolve(r.result);};
    });
    return connection;
  }
  async function transaction(seed, fn, write=false) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const t = db.transaction('state', write ? 'readwrite' : 'readonly');
      const store = t.objectStore('state');
      let result, failure;
      t.oncomplete = () => resolve(result);
      t.onabort = t.onerror = () => reject(failure || Error('保存失败或浏览器空间不足；请先导出备份。'));
      const r = store.get('root');
      r.onsuccess = () => {
        try {
          const root = r.result || {corpus:copy(seed), samples:[]};
          result = fn(root);
          if (write) store.put(root, 'root');
        } catch (e) {failure = e; t.abort();}
      };
    });
  }
  const bytes = audio => {
    if (typeof audio !== 'string' || audio.length > 2560200) throw Error('音频过大或编码无效。');
    return Uint8Array.from(atob(audio), c=>c.charCodeAt(0));
  };
  function duration(raw) {
    if (raw.length <= 44 || raw.length > 1920100) throw Error('音频大小无效。');
    const v = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
    const str = (p,n) => String.fromCharCode(...raw.subarray(p,p+n));
    // The application's recorder creates this canonical PCM16 WAV header.
    if (str(0,4)!=='RIFF'||str(8,4)!=='WAVE'||str(12,4)!=='fmt '||str(36,4)!=='data'||v.getUint32(16,true)!==16||v.getUint16(20,true)!==1||v.getUint16(22,true)!==1||v.getUint32(24,true)!==16000||v.getUint16(34,true)!==16||v.getUint32(40,true)!==raw.length-44||v.getUint32(4,true)!==raw.length-8) throw Error('请使用应用录制或转换的 16kHz PCM16 WAV。');
    const seconds = (raw.length-44)/32000;
    if (seconds<.3||seconds>60||(raw.length-44)%2) throw Error('语料须为 0.3–60 秒。');
    return seconds;
  }
  async function sample(data) {
    if(data.consent!==true||data.reviewed!==true) throw Error('须获得录音者授权，并由母语者核对标注。');
    if(!['train','dev','test'].includes(data.split)) throw Error('数据划分错误。');
    const raw=bytes(data.audio), seconds=duration(raw);
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
    return {audio:data.audio, meta:{id:crypto.randomUUID().replaceAll('-',''), speaker:cleanText(data.speaker,60,true),
      district:cleanText(data.district,60,true), reference:cleanText(data.reference,3000,true), mandarin:cleanText(data.mandarin||'',3000),
      raw_asr:cleanText(data.raw_asr||'',6000), model:cleanText(data.model||'manual',100), split:data.split, seconds,
      audio_sha256:hash, consent:true, reviewed:true, created_at:new Date().toISOString()}};
  }
  async function route(url, method, data, seed, validate) {
    if(url==='/api/corpus'&&method==='GET') return transaction(seed,r=>copy(r.corpus));
    if(url==='/api/corpus'&&method==='PUT') {
      const checked=await validate(data);
      return transaction(seed,r=>{
        if(data.revision!==r.corpus.revision) throw Error('另一标签页已修改词库，请重新加载并合并。');
        r.corpus={...checked,revision:r.corpus.revision+1};return copy(r.corpus);
      },true);
    }
    if(url==='/api/samples'&&method==='GET') return transaction(seed,r=>r.samples.map(s=>copy(s.meta)).reverse());
    if(url==='/api/samples'&&method==='POST') {
      const s=await sample(data);
      return transaction(seed,r=>{
        if(r.samples.length>=100) throw Error('最多保存 100 条，请导出整理后再添加。');
        if(r.samples.some(x=>x.meta.audio_sha256===s.meta.audio_sha256)) throw Error('这段音频已保存。');
        if(r.samples.some(x=>x.meta.speaker===s.meta.speaker&&x.meta.split!==s.meta.split)) throw Error('同一说话人不能跨 train/dev/test。');
        r.samples.push(s);return copy(s.meta);
      },true);
    }
    if(url.startsWith('/api/samples/')&&method==='DELETE') return transaction(seed,r=>{r.samples=r.samples.filter(s=>s.meta.id!==decodeURIComponent(url.split('/').pop()));return {ok:true};},true);
    throw Error('不支持的本地语料操作。');
  }
  function zip(files) {
    const table=Uint32Array.from({length:256},(_,n)=>{for(let j=0;j<8;j++)n=(n>>>1)^((n&1)?0xedb88320:0);return n>>>0;});
    const crc=a=>{let n=0xffffffff;for(const b of a)n=table[(n^b)&255]^(n>>>8);return (n^0xffffffff)>>>0;};
    const parts=[], directory=[];let offset=0,centralSize=0;
    for(const [path,value] of files) {
      const name=enc.encode(path),data=typeof value==='string'?enc.encode(value):value,checksum=crc(data);
      const header=new Uint8Array(30+name.length),h=new DataView(header.buffer);
      h.setUint32(0,0x04034b50,true);h.setUint16(4,20,true);h.setUint16(6,0x800,true);h.setUint16(12,33,true);
      h.setUint32(14,checksum,true);h.setUint32(18,data.length,true);h.setUint32(22,data.length,true);h.setUint16(26,name.length,true);header.set(name,30);
      const dir=new Uint8Array(46+name.length),d=new DataView(dir.buffer);
      d.setUint32(0,0x02014b50,true);d.setUint16(4,20,true);d.setUint16(6,20,true);d.setUint16(8,0x800,true);d.setUint16(14,33,true);
      d.setUint32(16,checksum,true);d.setUint32(20,data.length,true);d.setUint32(24,data.length,true);d.setUint16(28,name.length,true);d.setUint32(42,offset,true);dir.set(name,46);
      parts.push(header,data);directory.push(dir);offset+=header.length+data.length;centralSize+=dir.length;
    }
    const end=new Uint8Array(22),e=new DataView(end.buffer);e.setUint32(0,0x06054b50,true);e.setUint16(8,files.length,true);e.setUint16(10,files.length,true);e.setUint32(12,centralSize,true);e.setUint32(16,offset,true);
    return new Blob([...parts,...directory,end],{type:'application/zip'});
  }
  async function exportZip(seed) {
    const root=await transaction(seed,r=>copy(r));
    const manifest=root.samples.map(s=>({...s.meta,audio:`audio/${s.meta.id}.wav`}));
    const files=[['corpus.json',JSON.stringify(root.corpus,null,2)],['manifest.jsonl',manifest.map(m=>JSON.stringify(m)).join('\n')],
      ['NOTICE.txt','Private consented audio, not fine-tuned. Browser-local export. Keep test speakers out of training and prompts.\n']];
    for(const s of root.samples) files.push([`audio/${s.meta.id}.wav`,bytes(s.audio)]);
    return zip(files);
  }
  return {route,exportZip};
})();
