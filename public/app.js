'use strict';
const $=id=>document.getElementById(id);
let config={}, corpus={revision:0,terms:[],examples:[]}, rows=new Map(), ws=null, ac=null, mic=null, node=null;
let chunks=[], recording=false, stopping=false, uploading=false, uploadCancelled=false, timer=null, elapsed=0, audioBlob=null, audioUrl='';
let savedCorpus=null;
let session=0, queue=Promise.resolve(), flushResolve=null, streamModel='', streamRevision=0;
const stamp=n=>`${String(Math.floor(n/60)).padStart(2,'0')}:${String(Math.floor(n%60)).padStart(2,'0')}`;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.id);toast.id=setTimeout(()=>$('toast').hidden=true,6500);}
async function api(url,method='GET',data){
  if(config.storageMode==='browser'&&(url==='/api/corpus'||url.startsWith('/api/samples'))){
    if(!config.authenticated)throw Error('请先连接应用访问码。');
    return PutianStorage.route(url,method,data,config.seedCorpus,value=>api('/api/validate-corpus','POST',value));
  }
  if(config.storageMode==='browser'&&url==='/api/translate')data={...data,corpus:savedCorpus||config.seedCorpus};
  const opt={method,credentials:'same-origin',headers:{'Content-Type':'application/json'}};
  if(data!==undefined)opt.body=JSON.stringify(data);
  const r=await fetch(url,opt);let out;try{out=await r.json();}catch{throw Error('服务返回异常，请检查部署配置。');}
  if(!r.ok)throw Error(out.error||`请求失败 ${r.status}`);return out;
}
function safe(fn){return async(...args)=>{try{await fn(...args);}catch(e){toast(e.message||'操作失败。');}};}
function selectTab(name){document.querySelectorAll('.tab').forEach(t=>t.hidden=t.id!==name);document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));if(name==='samples'){$('sampleAudioInfo').textContent=audioBlob?`当前录音 ${elapsed.toFixed(1)} 秒。仅 0.3–60 秒可保存为单条语料。`:'请先录音或上传一段真实音频。';$('reference').value=[...rows.values()].filter(r=>r.final).map(r=>r.corrected||r.text).join('\n');}}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=safe(async()=>{selectTab(b.dataset.tab);if(b.dataset.tab==='samples'&&config.authenticated)await loadSamples();}));
async function refresh(){
  config=await api('/api/status');
  if(config.storageMode==='browser'&&!window.PutianStorage)await import('/local-store.js');
  $('storageNotice').textContent=config.storageNotice||'本地版：词库与音频保存于后端私有目录，不上传 GitHub。';
  if(config.storageMode==='browser')$('sampleStorage').textContent=config.storageNotice+' 同一浏览器的其他使用者可接触本地数据；请使用私人设备并导出备份。';
  $('clock').textContent=`${stamp(elapsed)} / ${stamp(config.maxSeconds||300)}`;
  $('connection').textContent=!config.keyConfigured?'后端尚未配置百炼密钥；可查看界面，不能真实识别。':!config.authenticated?'服务端已配置密钥，尚未验证有效性。请先连接应用访问码。':'已连接应用；云端连通性及莆仙话效果仍需真实录音验证。';
  $('settingsStatus').textContent=`密钥配置：${config.keyConfigured?'已配置（未实测）':'未配置'}。莆仙话专项验证：未完成。`;
  $('account').textContent=config.authenticated?'已连接 · 设置':'连接设置';
  if(config.authenticated){await loadCorpus();await loadSamples();}
}
$('account').onclick=()=>$('settings').showModal();$('closeSettings').onclick=()=>$('settings').close();
$('login').onclick=safe(async()=>{await api('/api/login','POST',{code:$('accessCode').value});$('accessCode').value='';await refresh();$('settings').close();toast('已连接。录音前请勾选音频授权。');});
$('logout').onclick=safe(async()=>{if(recording||ws)throw Error('请先结束识别。');await api('/api/logout','POST',{});await refresh();$('settings').close();});
$('engine').onchange=()=>{$('engineNote').textContent=$('engine').value==='collect'?'仅在浏览器内录音，不调用 ASR。标注并确认保存后才上传到本应用私有语料库。':$('engine').value==='qwen31'?'新流式接口：保留方言表达，并把人工热词传入识别请求。':$('engine').value==='qwen3'?'Qwen3 实时对照：官方接口不支持热词；不把无效参数伪装成优化。':'Fun-ASR 对照：使用领域上下文，不发送仅新接口支持的即时热词。';};
function requireAccess(){if(!config.authenticated){$('settings').showModal();throw Error('请先连接应用访问码。');}if($('engine').value!=='collect'&&!config.keyConfigured)throw Error('后端尚未配置百炼 API Key。');if(!$('consent').checked)throw Error('请先勾选录音者授权及云端识别同意。');}
function resetSession(){session++;rows.clear();$('segments').replaceChildren();$('empty').hidden=false;chunks=[];elapsed=0;audioBlob=null;streamModel='';$('reference').value='';$('mandarin').value='';$('sampleReviewed').checked=false;if(audioUrl)URL.revokeObjectURL(audioUrl);audioUrl='';$('playback').removeAttribute('src');$('playback').hidden=true;}
function button(text,click){const b=document.createElement('button');b.textContent=text;b.onclick=safe(click);return b;}
function receiveSegment(e){
  $('empty').hidden=true;let r=rows.get(e.id);
  if(r?.final&&!e.final)return;
  if(!r){r={id:e.id,text:'',final:false,corrected:'',translation:'',target:'',version:0};rows.set(e.id,r);const el=document.createElement('div');el.className='segment draft';
    r.meta=document.createElement('div');r.meta.className='segment-meta';r.raw=document.createElement('p');r.raw.className='raw';r.trans=document.createElement('p');r.trans.className='translation';
    r.controls=document.createElement('div');r.controls.className='actions';r.edit=document.createElement('textarea');r.edit.rows=2;r.edit.hidden=true;r.edit.setAttribute('aria-label','人工校正文本');
    r.controls.append(button('人工校正',async()=>{r.edit.hidden=!r.edit.hidden;if(!r.edit.hidden){r.edit.value=r.corrected||r.text;r.edit.focus();}}),button('翻译 / 重试',()=>translateRow(r)),button('朗读译文',async()=>{if(!r.translation)throw Error('尚无可朗读译文。');if(!window.speechSynthesis)throw Error('此浏览器不支持系统朗读。');speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(r.translation);u.lang=r.target==='en'?'en-US':'zh-CN';speechSynthesis.speak(u);}));
    r.edit.oninput=()=>{r.corrected=r.edit.value.trim();r.version++;r.translation='';r.trans.textContent='已校正；请点击翻译。原始转写未被覆盖。';};el.append(r.meta,r.raw,r.edit,r.trans,r.controls);$('segments').append(el);r.el=el;
  }
  const wasFinal=r.final,old=r.text;r.text=e.text;r.final=e.final;r.meta.textContent=e.final?'最终转写 · 仍须人工核对':'实时草稿 · 内容可能变化';r.el.classList.toggle('draft',!e.final);r.raw.textContent=e.text;r.controls.hidden=!e.final;
  if(old!==e.text)r.version++;
  if(e.final&&(!wasFinal||old!==e.text)&&$('autoTranslate').checked)enqueue(r);
}
function enqueue(r){const run=session;queue=queue.catch(()=>{}).then(async()=>{if(run===session)await translateRow(r);}).catch(e=>toast(e.message));}
async function translateRow(r){
  if(!r.final)return;const source=r.corrected||r.text;if(!source.trim())return;
  const target=$('target').value,run=session,version=++r.version;
  r.trans.textContent='正在翻译…';
  try{const out=await api('/api/translate','POST',{text:source,target});if(session!==run||r.version!==version||$('target').value!==target)return;r.translation=out.text;r.target=target;r.trans.textContent=out.text;}
  catch(e){if(session===run&&r.version===version)r.trans.textContent=`翻译未完成：${e.message}`;}
}
$('target').onchange=()=>{for(const r of rows.values()){r.version++;r.translation='';r.trans.textContent='译文语言已切换，请重新翻译。';}};
function connectStream(){
  return new Promise((resolve,reject)=>{
    const sock=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);ws=sock;let ready=false;
    const timeout=setTimeout(()=>{reject(Error('连接等待超时。'));sock.close();},26000);
    sock.onopen=()=>sock.send(JSON.stringify({type:'start',engine:$('engine').value,district:$('district').value,silence:Number($('silence').value),enhance:$('enhance').checked,consent:true,...(config.storageMode==='browser'?{corpus:savedCorpus||config.seedCorpus,corpusRevision:(savedCorpus||config.seedCorpus).revision}:{})}));
    sock.onmessage=event=>{let msg;try{msg=JSON.parse(event.data);}catch{return;}
      if(msg.type==='ready'){ready=true;clearTimeout(timeout);resetSession();streamModel=msg.model;streamRevision=msg.corpusRevision;$('resultStatus').textContent='实时接收';resolve(sock);}
      if(msg.type==='segment')receiveSegment(msg);
      if(msg.type==='done'){$('resultStatus').textContent='转写结束';sock.close();}
      if(msg.type==='error'){toast(msg.message);$('resultStatus').textContent='中断 · 已保留原文';if(!ready)reject(Error(msg.message));sock.close();}
    };
    sock.onerror=()=>{if(!ready)reject(Error('WebSocket 连接失败；检查访问码、HTTPS、云平台 WebSocket 配置及百炼密钥。'));};
    sock.onclose=()=>{clearTimeout(timeout);if(!ready)reject(Error('识别连接未建立。'));if(ws===sock)ws=null;if(recording&&!stopping)void stopCapture(false);if(uploading)uploadCancelled=true;if($('resultStatus').textContent==='实时接收')$('resultStatus').textContent='连接已断开 · 草稿未确认';$('record').disabled=false;};
  });
}
function sendPcm(buffer){
  if(streamModel==='local-collection'){chunks.push(new Uint8Array(buffer));elapsed+=buffer.byteLength/32000;$('clock').textContent=`${stamp(elapsed)} / ${stamp(config.maxSeconds||300)}`;return;}
  if(!ws||ws.readyState!==WebSocket.OPEN)return;
  if(ws.bufferedAmount>32000*3){toast('网络积压超过 3 秒，已停止发送，避免悄悄丢音。');void stopCapture(false);ws?.close();return;}
  chunks.push(new Uint8Array(buffer));elapsed+=buffer.byteLength/32000;ws.send(buffer);$('clock').textContent=`${stamp(elapsed)} / ${stamp(config.maxSeconds||300)}`;
}
function wave(level=0){const c=$('wave'),g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);g.fillStyle=recording?'#cb5132':'#b9c3ad';for(let i=0;i<63;i++){const h=Math.max(2,Math.min(90,level*700*(.5+.5*Math.sin(i*1.63)**2)));g.fillRect(i*c.width/63+2,(c.height-h)/2,3,h);}}
async function startCapture(){
  requireAccess();if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('录音需要 HTTPS 或本机 localhost。手机不要通过局域网 HTTP 录音。');
  $('record').disabled=true;$('recordStatus').textContent='连接麦克风与识别服务…';
  try{
    ac=new (window.AudioContext||window.webkitAudioContext)({sampleRate:16000});await ac.resume();
    mic=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
    if(!ac.audioWorklet)throw Error('此浏览器不支持 AudioWorklet；请换系统浏览器或上传音频。');
    await ac.audioWorklet.addModule('/capture.js');if($('engine').value==='collect'){resetSession();streamModel='local-collection';$('resultStatus').textContent='仅采集 · 无识别结果';}else await connectStream();
    node=new AudioWorkletNode(ac,'putian-capture');node.port.onmessage=e=>{if(e.data.pcm)sendPcm(e.data.pcm);if(e.data.level!==undefined)wave(e.data.level);if(e.data.flushed&&flushResolve){flushResolve();flushResolve=null;}};
    const source=ac.createMediaStreamSource(mic),mute=ac.createGain();mute.gain.value=0;source.connect(node);node.connect(mute);mute.connect(ac.destination);
    recording=true;stopping=false;$('record').textContent='■ 结束并收尾';$('recordStatus').textContent=streamModel==='local-collection'?'本地录音 · 请在标注语料页人工转写':'正在聆听 · 边说边出字';document.querySelector('.stage').classList.add('live');$('upload').disabled=true;
    timer=setTimeout(()=>void stopCapture(true),((config.maxSeconds||300)-1)*1000);
  }catch(e){mic?.getTracks().forEach(t=>t.stop());mic=null;if(ac){await ac.close().catch(()=>{});ac=null;}ws?.close();$('recordStatus').textContent='未开始';throw e;}
  finally{$('record').disabled=false;}
}
function makeWav(data){const size=data.reduce((n,c)=>n+c.byteLength,0),out=new ArrayBuffer(44+size),v=new DataView(out);const s=(p,t)=>[...t].forEach((c,i)=>v.setUint8(p+i,c.charCodeAt(0)));s(0,'RIFF');v.setUint32(4,size+36,true);s(8,'WAVE');s(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,size,true);let p=44;for(const chunk of data){new Uint8Array(out,p,chunk.length).set(chunk);p+=chunk.length;}return new Blob([out],{type:'audio/wav'});}
function retainAudio(){if(chunks.length){audioBlob=makeWav(chunks);if(audioUrl)URL.revokeObjectURL(audioUrl);audioUrl=URL.createObjectURL(audioBlob);$('playback').src=audioUrl;$('playback').hidden=false;}}
async function stopCapture(sendStop=true){
  if(stopping)return;stopping=true;$('record').disabled=true;clearTimeout(timer);
  if(uploading){uploadCancelled=true;return;}
  try{if(node){await new Promise(resolve=>{flushResolve=resolve;node.port.postMessage('stop');setTimeout(resolve,600);});node.disconnect();node=null;}}
  finally{mic?.getTracks().forEach(t=>t.stop());mic=null;if(ac){await ac.close().catch(()=>{});ac=null;}recording=false;retainAudio();wave();document.querySelector('.stage').classList.remove('live');$('record').textContent='● 开始实时识别';$('recordStatus').textContent='已停止录音';$('upload').disabled=false;stopping=false;}
  if(sendStop&&ws?.readyState===WebSocket.OPEN){$('resultStatus').textContent='等待句尾结果…';ws.send(JSON.stringify({type:'stop'}));}else{$('record').disabled=false;}
}
$('record').onclick=safe(async()=>{if(recording||uploading)await stopCapture(true);else await startCapture();});
$('upload').onclick=()=>{$('audioFile').value='';$('audioFile').click();};
$('audioFile').onchange=safe(async()=>{
  const file=$('audioFile').files[0];if(!file)return;requireAccess();if(file.size>20*1024*1024)throw Error('上传音频最多 20 MB。');
  $('record').disabled=true;$('upload').disabled=true;
  try{const decoder=new AudioContext();let decoded;try{decoded=await decoder.decodeAudioData(await file.arrayBuffer());}finally{await decoder.close();}
    if(decoded.duration<.3||decoded.duration>(config.maxSeconds||300))throw Error(`音频须为 0.3 秒至 ${config.maxSeconds||300} 秒。`);
    const offline=new OfflineAudioContext(1,Math.ceil(decoded.duration*16000),16000);const src=offline.createBufferSource();src.buffer=decoded;src.connect(offline.destination);src.start();const rendered=await offline.startRendering(),f=rendered.getChannelData(0);
    if($('engine').value==='collect'){resetSession();streamModel='local-collection';$('resultStatus').textContent='仅采集 · 无识别结果';}else await connectStream();uploading=true;uploadCancelled=false;$('record').disabled=false;$('record').textContent='■ 停止发送';$('recordStatus').textContent='按原速发送文件音频';
    const start=performance.now();for(let pos=0;pos<f.length&&!uploadCancelled;pos+=1600){const n=Math.min(1600,f.length-pos),buf=new ArrayBuffer(n*2),v=new DataView(buf);for(let i=0;i<n;i++){const x=Math.max(-1,Math.min(1,f[pos+i]));v.setInt16(i*2,Math.round(x*(x<0?32768:32767)),true);}sendPcm(buf);await new Promise(r=>setTimeout(r,Math.max(0,start+(pos+n)/16-performance.now())));}
    retainAudio();if(ws?.readyState===WebSocket.OPEN){$('record').disabled=true;ws.send(JSON.stringify({type:'stop'}));$('resultStatus').textContent='等待句尾结果…';}
  }finally{uploading=false;stopping=false;$('record').textContent='● 开始实时识别';$('upload').disabled=false;if(!ws)$('record').disabled=false;$('recordStatus').textContent='音频发送已停止';}
});
$('clear').onclick=safe(async()=>{if(ws||recording||uploading)throw Error('请先结束识别。');resetSession();$('resultStatus').textContent='等待输入';wave();});
function download(name,blob){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
$('downloadText').onclick=()=>{const data={model:streamModel,corpusRevision:streamRevision,district:$('district').value,dialectValidated:false,fineTuned:false,segments:[...rows.values()].map(r=>({raw:r.text,final:r.final,corrected:r.corrected,translation:r.translation,target:r.target}))};download('putian-transcript.json',new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));};
async function loadCorpus(){corpus=await api('/api/corpus');savedCorpus=structuredClone(corpus);renderCorpus();}
function renderCorpus(){
  $('revision').textContent=`版本 ${corpus.revision} · ${corpus.terms.length} 词`;$('termList').replaceChildren();
  corpus.terms.forEach((t,i)=>{const el=document.createElement('div');el.className='chip';const title=document.createElement('span');title.textContent=`${t.text} · ${t.weight}${t.meaning?' / '+t.meaning:''}`;el.append(title,button('×',async()=>{corpus.terms.splice(i,1);renderCorpus();}));$('termList').append(el);});
  $('exampleList').replaceChildren();corpus.examples.forEach((e,i)=>{const el=document.createElement('div');el.className='row';const text=document.createElement('p');text.textContent=`${e.source} → ${e.target}`;el.append(text,button('删除',async()=>{corpus.examples.splice(i,1);renderCorpus();}));$('exampleList').append(el);});
}
$('reloadCorpus').onclick=safe(loadCorpus);
$('addTerm').onclick=safe(async()=>{const text=$('termText').value.trim();if(!text)throw Error('请填写热词。');if(corpus.terms.some(t=>t.text===text))throw Error('词条已存在；先删除旧项再修改。');corpus.terms.push({text,weight:Number($('termWeight').value),meaning:$('termMeaning').value.trim()});$('termText').value='';$('termMeaning').value='';renderCorpus();});
$('addExample').onclick=safe(async()=>{if(!$('exampleReviewed').checked)throw Error('例句需要母语者确认。');const source=$('exampleSource').value.trim(),target=$('exampleTarget').value.trim();if(!source||!target)throw Error('请填写完整的对应关系。');corpus.examples.push({source,target,reviewed:true});$('exampleSource').value='';$('exampleTarget').value='';$('exampleReviewed').checked=false;renderCorpus();});
$('saveCorpus').onclick=safe(async()=>{corpus=await api('/api/corpus','PUT',corpus);savedCorpus=structuredClone(corpus);renderCorpus();toast('已保存。热词从下一次识别生效；这不是微调。');});
$('exportCorpus').onclick=()=>download('putian-glossary.json',new Blob([JSON.stringify(corpus,null,2)],{type:'application/json'}));
$('importCorpus').onclick=()=>{$('corpusFile').value='';$('corpusFile').click();};
$('corpusFile').onchange=safe(async()=>{const f=$('corpusFile').files[0];if(!f)return;if(f.size>200000)throw Error('词库文件最多 200KB。');const v=JSON.parse(await f.text());if(!Array.isArray(v.terms)||!Array.isArray(v.examples))throw Error('文件须包含 terms 和 examples 数组。');if(v.terms.length>500||v.examples.length>100)throw Error('词库超过数量限制。');corpus={revision:corpus.revision,terms:v.terms,examples:v.examples};renderCorpus();toast('已导入到编辑区，检查后点击保存。');});
async function loadSamples(){const list=await api('/api/samples');$('sampleList').replaceChildren();if(!list.length){$('sampleList').textContent='还没有真实标注语料；未运行微调。';return;}for(const s of list){const el=document.createElement('div');el.className='row';const p=document.createElement('p');p.textContent=`${s.speaker} · ${s.district} · ${s.split} · ${s.seconds.toFixed(1)}s — ${s.reference}`;el.append(p,button('删除',async()=>{if(confirm('删除这条私有音频与标注？')){await api('/api/samples/'+encodeURIComponent(s.id),'DELETE');await loadSamples();}}));$('sampleList').append(el);}}
$('saveSample').onclick=safe(async()=>{if(!audioBlob)throw Error('没有可保存的真实音频。');if(elapsed>60||elapsed<.3)throw Error('语料单段需为 0.3–60 秒，请录制短句。');if(!$('sampleReviewed').checked)throw Error('请确认母语者核对与语料保存授权。');const bytes=new Uint8Array(await audioBlob.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=8192)bin+=String.fromCharCode(...bytes.subarray(i,i+8192));await api('/api/samples','POST',{audio:btoa(bin),speaker:$('speaker').value,split:$('split').value,district:$('district').value,reference:$('reference').value,mandarin:$('mandarin').value,raw_asr:[...rows.values()].map(r=>r.text).join('\n'),model:streamModel||'manual',consent:true,reviewed:true});await loadSamples();$('sampleReviewed').checked=false;toast('真实音频与人工标注已保存；模型权重没有改变。');});
$('exportDataset').onclick=safe(async()=>{if(config.storageMode==='browser'){if(!config.authenticated)throw Error('请先连接应用。');download('putian-private-corpus.zip',await PutianStorage.exportZip(config.seedCorpus));return;}const r=await fetch('/api/export');if(!r.ok)throw Error('导出失败，请先连接应用。');download('putian-private-corpus.zip',await r.blob());});
window.addEventListener('pagehide',()=>{mic?.getTracks().forEach(t=>t.stop());ws?.close();});
wave();void refresh().catch(e=>{$('connection').textContent='后端未连接。请通过运行中的应用网址打开，不要直接双击 HTML。';toast(e.message);});
