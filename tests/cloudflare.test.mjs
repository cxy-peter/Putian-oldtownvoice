import {test} from 'node:test';import assert from 'node:assert/strict';import worker from '../cloudflare/worker.mjs';
const env={UPSTREAM_ORIGIN:'https://putian-demo.vercel.app'};
test('rejects unset upstream',async()=>assert.equal((await worker.fetch(new Request('https://voice.example.com'),{})).status,503));
test('rejects arbitrary proxy target',async()=>assert.equal((await worker.fetch(new Request('https://voice.example.com'),{UPSTREAM_ORIGIN:'https://evil.invalid'})).status,503));
test('rejects cross-origin POST',async()=>assert.equal((await worker.fetch(new Request('https://voice.example.com/api/login',{method:'POST',headers:{Origin:'https://evil.invalid'}}),env)).status,403));
test('rejects cross-origin WS',async()=>assert.equal((await worker.fetch(new Request('https://voice.example.com/ws',{headers:{Upgrade:'websocket',Origin:'https://evil.invalid'}}),env)).status,403));
test('forwards exact path and origin, retains cookie, disables cache',async()=>{
 const saved=globalThis.fetch;let sent;
 globalThis.fetch=async req=>{sent=req;return new Response('{}',{headers:{'Set-Cookie':'pv_cloud_session=fixture; HttpOnly; Secure'}});};
 try{const r=await worker.fetch(new Request('https://voice.example.com/api/login',{method:'POST',headers:{Origin:'https://voice.example.com'},body:'{}'}),env);assert.equal(sent.url,'https://putian-demo.vercel.app/api/login');assert.equal(sent.headers.get('Origin'),'https://voice.example.com');assert.equal(r.headers.get('Cache-Control'),'no-store');assert.ok(r.headers.get('Set-Cookie'));}finally{globalThis.fetch=saved;}
});
test('101 response object preserved for WebSocket upgrade',async()=>{
 const saved=globalThis.fetch;const sentinel={status:101,webSocket:{}};globalThis.fetch=async()=>sentinel;
 try{const r=await worker.fetch(new Request('https://voice.example.com/ws',{headers:{Upgrade:'websocket',Origin:'https://voice.example.com'}}),env);assert.equal(r,sentinel);}finally{globalThis.fetch=saved;}
});
