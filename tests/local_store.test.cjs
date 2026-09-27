// Tests the IndexedDB adapter against an in-memory event/transaction fixture.
// Does NOT claim to test actual browser persistence or quota behavior.
const {test}=require('node:test');const assert=require('node:assert/strict');
const {readFileSync,writeFileSync}=require('node:fs');const vm=require('node:vm');const {webcrypto}=require('node:crypto');
function fixture(){
 let root,tail=Promise.resolve();
 const db={createObjectStore(){},close(){},transaction(name,mode){
   let resolveDone;const done=new Promise(r=>resolveDone=r);let aborted=false;const prev=tail;tail=done;
   const t={abort(){aborted=true;queueMicrotask(()=>{t.onabort?.();resolveDone();});},objectStore(){return {
     get(){const r={};prev.then(()=>queueMicrotask(()=>{r.result=root?structuredClone(root):undefined;r.onsuccess?.();queueMicrotask(()=>{if(!aborted)t.oncomplete?.();resolveDone();});}));return r;},
     put(v){if(!aborted)root=structuredClone(v);}
   };}};return t;
 }};
 const idb={open(){const r={result:db};queueMicrotask(()=>{r.onupgradeneeded?.();r.onsuccess?.();});return r;}};
 const window={indexedDB:idb};const ctx={window,indexedDB:idb,TextEncoder,structuredClone,Uint8Array,Uint32Array,DataView,Blob,crypto:webcrypto,atob};
 vm.runInNewContext(readFileSync('public/local-store.js','utf8'),ctx);return window.PutianStorage;
}
const seed={revision:1,terms:[{text:'莆田',weight:3,meaning:''}],examples:[]};
const validate=async c=>({terms:c.terms,examples:c.examples});
function sample(value=0){const b=Buffer.alloc(32044);b.write('RIFF');b.writeUInt32LE(32036,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(16000,24);b.writeUInt32LE(32000,28);b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(32000,40);b.writeInt16LE(value,44);return {audio:b.toString('base64'),speaker:'s1',district:'莆田城区',reference:'合成标注测试',split:'train',consent:true,reviewed:true};}
test('glossary seed and version persist in adapter',async()=>{const s=fixture();const c=await s.route('/api/corpus','GET',null,seed,validate);assert.equal(c.revision,1);c.terms.push({text:'仙游',weight:3,meaning:''});await s.route('/api/corpus','PUT',c,seed,validate);assert.equal((await s.route('/api/corpus','GET',null,seed,validate)).revision,2);});
test('stale corpus revision rejected',async()=>{const s=fixture();await s.route('/api/corpus','PUT',seed,seed,validate);await assert.rejects(s.route('/api/corpus','PUT',seed,seed,validate),/标签页/);});
test('validation failure cannot commit edits',async()=>{const s=fixture();await assert.rejects(s.route('/api/corpus','PUT',seed,seed,async()=>{throw Error('invalid');}));assert.equal((await s.route('/api/corpus','GET',null,seed,validate)).revision,1);});
test('annotated sample roundtrip and delete',async()=>{const s=fixture();const m=await s.route('/api/samples','POST',sample(),seed);assert.equal(m.seconds,1);assert.equal((await s.route('/api/samples','GET',null,seed)).length,1);await s.route('/api/samples/'+m.id,'DELETE',null,seed);assert.equal((await s.route('/api/samples','GET',null,seed)).length,0);});
test('duplicate audio rejected',async()=>{const s=fixture();await s.route('/api/samples','POST',sample(),seed);await assert.rejects(s.route('/api/samples','POST',sample(),seed),/已保存/);});
test('speaker cannot cross train/test',async()=>{const s=fixture();await s.route('/api/samples','POST',sample(),seed);await assert.rejects(s.route('/api/samples','POST',{...sample(200),split:'test'},seed),/不能跨/);});
test('consent required',async()=>{await assert.rejects(fixture().route('/api/samples','POST',{...sample(),consent:false},seed),/授权/);});
test('review required',async()=>{await assert.rejects(fixture().route('/api/samples','POST',{...sample(),reviewed:false},seed),/标注/);});
test('non-wav and malformed fields rejected',async()=>{await assert.rejects(fixture().route('/api/samples','POST',{...sample(),audio:'YWJj'},seed));await assert.rejects(fixture().route('/api/samples','POST',{...sample(),speaker:''},seed));});
test('local dataset ZIP generated for external validation',async()=>{const s=fixture();await s.route('/api/samples','POST',sample(),seed);const blob=await s.exportZip(seed);assert.equal(blob.type,'application/zip');const b=Buffer.from(await blob.arrayBuffer());assert.equal(b.readUInt32LE(),0x04034b50);if(process.env.TEST_ZIP)writeFileSync(process.env.TEST_ZIP,b);});
