'use strict';
const $=id=>document.getElementById(id);
let unlocked=false,busy=false,selected=null,wav=null,recorder=null,stream=null,timer=null,seconds=0,audioURL='';
let sourceEntries=[],referenceIDs=[],recordEntry=null;
function notice(t){$('notice').textContent=t;}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function tab(name){document.querySelectorAll('.pane').forEach(n=>n.hidden=n.id!=='pane-'+name);document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===name));}
document.querySelectorAll('[data-tab]').forEach(n=>n.onclick=()=>tab(n.dataset.tab));
async function api(path,body){
  const ctl=new AbortController(),time=setTimeout(()=>ctl.abort(),115000);
  try{const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:ctl.signal});
    const d=await r.json().catch(()=>({error:'服务响应格式错误。'}));if(!r.ok){if(r.status===401){unlocked=false;controls();}throw new Error(d.error||'请求失败');}return d;
  }finally{clearTimeout(time);}
}
function controls(){
  $('login-form').hidden=unlocked;
  ['direct','match','save-audio'].forEach(id=>$(id).disabled=!unlocked||!wav||busy||!!recorder);
  $('assisted').disabled=!unlocked||!wav||busy||!!recorder||!referenceIDs.length;
  $('record').disabled=busy||!!recorder;$('stop').disabled=!recorder;$('audio-file').disabled=busy||!!recorder;
  $('import-submit').disabled=!unlocked||busy;$('export-all').disabled=!unlocked||busy;
}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);}
function encode64(buf){let s='';const b=new Uint8Array(buf);for(let i=0;i<b.length;i+=16384)s+=String.fromCharCode(...b.subarray(i,i+16384));return btoa(s);}
function wavBytes(x){const b=new ArrayBuffer(44+x.length*2),v=new DataView(b);const str=(n,s)=>[...s].forEach((c,i)=>v.setUint8(n+i,c.charCodeAt(0)));str(0,'RIFF');v.setUint32(4,b.byteLength-8,true);str(8,'WAVE');str(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);str(36,'data');v.setUint32(40,x.length*2,true);for(let i=0;i<x.length;i++){const s=Math.max(-1,Math.min(1,x[i]));v.setInt16(44+i*2,Math.round(s<0?s*32768:s*32767),true);}return b;}
async function loadAudio(blob){
  if(blob.size>15*1024*1024)throw new Error('请选择 15 MB 以内的短音频。');
  const AC=window.AudioContext||window.webkitAudioContext,ctx=new AC();let data;
  try{data=await ctx.decodeAudioData(await blob.arrayBuffer());}finally{await ctx.close();}
  if(data.duration<.3||data.duration>30)throw new Error('录音须为 0.3–30 秒；不会自动截断。');
  const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;
  const off=new Offline(1,Math.round(data.duration*16000),16000),s=off.createBufferSource();s.buffer=data;s.connect(off.destination);s.start();
  wav=wavBytes((await off.startRendering()).getChannelData(0));
  if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(blob);$('current-audio').src=audioURL;
  $('audio-note').textContent=`${data.duration.toFixed(2)} 秒 · 原音可回放 · 请求统一为 16 kHz PCM WAV`;
  $('direct-result').textContent='尚未运行。';$('assisted-result').textContent='尚未运行参考辅助。';$('direct-info').textContent='';
  $('match-list').replaceChildren();referenceIDs=[];$('mandarin').value='';
  ['human','reviewed','store-consent','allow-reference','training','reference-cloud-consent'].forEach(id=>$(id).checked=false);
  notice('已载入原音。人工答案不进入直接翻译请求。');controls();
}
function stopTracks(){if(timer)clearInterval(timer);timer=null;if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;recorder=null;controls();}
$('record').onclick=async()=>{if(busy||recorder)return;busy=true;controls();try{
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw new Error('当前浏览器无法录音，请使用 HTTPS 或上传音频。');
  stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
  const type=['audio/webm;codecs=opus','audio/mp4','audio/webm'].find(t=>MediaRecorder.isTypeSupported(t));
  recorder=new MediaRecorder(stream,type?{mimeType:type}:{});const chunks=[],current=recorder;
  current.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
  current.onerror=()=>{stopTracks();notice('录音失败，请重新授权或上传文件。');};
  current.onstop=async()=>{const blob=new Blob(chunks,{type:current.mimeType});stopTracks();busy=true;controls();try{await loadAudio(blob);}catch(e){notice(e.message);}finally{busy=false;controls();}};
  current.start(250);busy=false;seconds=0;$('timer').textContent='00:00';timer=setInterval(()=>{seconds++;$('timer').textContent='00:'+String(seconds).padStart(2,'0');if(seconds>=20&&recorder?.state==='recording')recorder.stop();},1000);controls();notice('录制中，20 秒自动停止。');
}catch(e){busy=false;stopTracks();notice(e.name==='NotAllowedError'?'请允许麦克风或上传音频。':e.message);}};
$('stop').onclick=()=>{if(recorder?.state==='recording')recorder.stop();};
$('audio-file').onchange=async()=>{const f=$('audio-file').files[0];if(!f)return;busy=true;controls();try{await loadAudio(f);}catch(e){notice(e.message);}finally{busy=false;controls();$('audio-file').value='';}};
async function refresh(){
  const d=await api('/api/lab/status');$('count-entries').textContent=d.stats.entries;$('count-audio').textContent=d.stats.local_audio;$('count-reference').textContent=d.stats.reference_audio;
  $('connection').textContent='已连接现有项目 · 私有语料工作台';
  $('match-note').textContent=d.acoustic_available?'只检索已审核、允许参考的本机录音。相同文件和 dev/test 不参与。':'声音检索需安装 numpy：python -m pip install numpy。查词与录音保存不受影响。';
  $('source-list').replaceChildren(...d.sources.map(s=>{const div=node('div',undefined,'source'),a=node('a',s.id);a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';div.append(a,node('p',s.useful_for),node('p','状态：'+s.verification),node('p','边界：'+s.rights_note));return div;}));
}
async function search(){const d=await api('/api/lab/search?q='+encodeURIComponent($('query').value));sourceEntries=d.entries;$('search-count').textContent=d.total+' 条匹配';
  $('entry-list').replaceChildren(...d.entries.map(e=>{const b=node('button',undefined,'entry'+(selected?.id===e.id?' selected':'')),left=node('div'),right=node('span',e.status==='reference_only'?'字词参考':'待审核','entry-kind');b.type='button';left.append(node('strong',e.word),node('small',e.pinyin||e.ipa||'暂无标音'));b.append(left,right);b.onclick=()=>selectEntry(e);return b;}));
  if(!d.entries.length)$('entry-list').append(node('p','没有匹配词条；不会用近音字强配词义。','empty'));
  if(d.entries.length&&(!selected||!d.entries.some(e=>e.id===selected.id)))selectEntry(d.entries[0]);
}
function selectEntry(e){selected=e;const box=$('entry-detail');box.replaceChildren(node('span',e.status==='reference_only'?'字词编码参考 · 未审核':'外部导入 · 待核对','badge'),node('h2',e.word),node('p',e.pinyin||e.ipa||'暂无标音','phonetic'));
  const dl=node('dl',undefined,'meta');for(const [k,v] of [['口音',e.district],['原始释义',e.mandarin?.join('；')||'来源未提供已审核的普通话含义'],['检索别名',e.aliases?.join(' / ')||'无'],['真人音频',e.audio_url?'仅有外部链接，未下载、未试听确认':'尚无关联真人音频'],['来源状态',e.rights_note]]){dl.append(node('dt',k),node('dd',v));}box.append(dl);
  if(e.source_url){const a=node('a','查看原始来源 ↗');a.href=e.source_url;a.target='_blank';a.rel='noopener noreferrer';box.append(a);}
  const p=node('p',e.note,'small'),b=node('button','为这个词补录原音');b.type='button';b.onclick=()=>{recordEntry=e;tab('audio');$('record-target').textContent='关联词条：'+e.word+' / '+(e.pinyin||'未标音')+'（不会作为直译提示）';$('mandarin').value='';notice('请用实际口音说完整短句，再核对含义。');};box.append(p,b);
  document.querySelectorAll('.entry').forEach((el,i)=>el.classList.toggle('selected',sourceEntries[i]?.id===e.id));
}
$('clear-entry').onclick=()=>{recordEntry=null;$('record-target').textContent='当前不关联词条。';notice('已清除关联，不影响原音。');};
$('search-form').onsubmit=e=>{e.preventDefault();search().catch(x=>notice(x.message));};
document.querySelectorAll('[data-query]').forEach(b=>b.onclick=()=>{$('query').value=b.dataset.query;search().catch(e=>notice(e.message));});
$('login-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/login',{code:$('code').value});$('code').value='';unlocked=true;await refresh();await search();await refreshSamples();notice('已导入的参考词条已显示。真人音频数量独立统计。');}catch(x){notice(x.message);}finally{controls();}};
async function runInfer(assisted=false){
  if(!wav||busy)return;if(!$('cloud-consent').checked){notice('请先同意发送本段录音到百炼。');return;}
  busy=true;controls();notice('正在依据原音生成普通话候选；没有修改模型权重。');
  try{const r=await api('/api/lab/infer',{audio:encode64(wav),model:$('model').value,consent_cloud:true,reference_ids:assisted?referenceIDs:[],consent_reference_cloud:$('reference-cloud-consent').checked});
    $(assisted?'assisted-result':'direct-result').textContent=r.candidate;$('direct-info').textContent=`${r.model} · ${r.seconds}s · 参考 ${r.reference_ids.length} 条 · 待母语者核对`;notice('完成。请回听，不用文字是否通顺判断准确率。');
  }catch(e){notice(e.name==='AbortError'?'请求超时，保留原音和此前结果。':e.message);}finally{busy=false;controls();}
}
$('direct').onclick=()=>runInfer(false);$('assisted').onclick=()=>runInfer(true);
$('match').onclick=async()=>{if(!wav||busy)return;busy=true;controls();notice('在本机比较已授权参考录音，不调用百炼。');try{const r=await api('/api/lab/match',{audio:encode64(wav)});referenceIDs=[];$('match-note').textContent=r.message+` 比较 ${r.compared} 条；排除同一文件 ${r.identical_excluded} 条。`;
  $('match-list').replaceChildren(...r.matches.map(m=>{const div=node('div',undefined,'match-card'),label=node('label',undefined,'check'),c=node('input');c.type='checkbox';c.onchange=()=>{referenceIDs=c.checked?[...referenceIDs,m.id]:referenceIDs.filter(x=>x!==m.id);controls();};label.append(c,node('span',m.mandarin));const a=node('audio');a.controls=true;a.preload='none';a.src=m.audio_path;div.append(label,node('p',`${m.district} · ${m.speaker_id} · 距离 ${m.distance}（不是概率）`,'small'),a);return div;}));notice('候选仅供回听比较，未自动替换译文。');
}catch(e){notice(e.message);}finally{busy=false;controls();}};
$('save-audio').onclick=async()=>{if(!wav||busy)return;busy=true;controls();try{await api('/api/lab/save',{audio:encode64(wav),entry_id:recordEntry?.id||null,mandarin:$('mandarin').value,speaker:$('speaker').value,reviewer:$('reviewer').value,district:$('district').value,split:$('split').value,human_confirmed:$('human').checked,reviewed:$('reviewed').checked,consent_store:$('store-consent').checked,allow_reference:$('allow-reference').checked,training_allowed:$('training').checked});await refresh();await refreshSamples();notice('音频和人工含义已保存。下一次本机检索可用，但没有微调模型。');}catch(e){notice(e.message);}finally{busy=false;controls();}};
async function refreshSamples(){const d=await api('/api/lab/samples');$('sample-list').replaceChildren(...d.samples.map(r=>{const div=node('div',undefined,'sample'),a=node('audio');a.controls=true;a.preload='none';a.src='/api/lab/audio/'+r.id;div.append(node('h3',r.mandarin),node('p',`${r.district} · ${r.speaker_id} · ${r.audio.seconds}s · ${r.split}`,'small'),node('p',r.allow_reference?'已允许检索（dev/test 仍排除）':'仅保存，不作检索参考','small'),a);return div;}));if(!d.samples.length)$('sample-list').append(node('p','目前 0 条真人音频。先补录一段，不用合成音冒充结果。','empty'));}
$('refresh-samples').onclick=()=>refreshSamples().catch(e=>notice(e.message));
$('export-all').onclick=async()=>{try{const r=await fetch('/api/lab/export',{credentials:'same-origin'});if(!r.ok)throw new Error('导出失败，请检查登录状态。');download(await r.blob(),'private-corpus-workbench.zip');notice('私有备份已导出，请勿公开上传原始录音。');}catch(e){notice(e.message);}};
$('import-kind').onchange=()=>{$('manual-input').hidden=$('import-kind').value!=='manual';$('edialect-input').hidden=$('import-kind').value!=='edialect';};
async function fileText(file){if(!file)throw new Error('请选择本地文件。');if(file.size>1_600_000)throw new Error('每个文件上限 1.6 MB，请分批导入。');return(await file.text()).replace(/^\uFEFF/,'');}
function records(text){text=text.trim();if(!text)throw new Error('请提供 JSON/JSONL。');try{const v=JSON.parse(text);return Array.isArray(v)?v:[v];}catch{try{return text.split(/\r?\n/).filter(l=>l.trim()).map(l=>JSON.parse(l));}catch{throw new Error('JSON/JSONL 格式错误。');}}}
$('manual-file').onchange=async()=>{try{$('manual-json').value=await fileText($('manual-file').files[0]);}catch(e){notice(e.message);}};
$('import-submit').onclick=async()=>{if(busy)return;if(!$('process-consent').checked){notice('请确认有权处理材料。');return;}busy=true;controls();try{const body={kind:$('import-kind').value,source_name:$('source-name').value,source_base:$('source-base').value,consent_process:true};if(body.kind==='manual')body.records=records($('manual-json').value);else{body.words=JSON.parse(await fileText($('words-file').files[0]));body.pronunciations=$('pron-file').files[0]?JSON.parse(await fileText($('pron-file').files[0])):[];}
  const r=await api('/api/lab/import',body);$('import-report').textContent=`实际新增：${r.imported} 条\n重复跳过：${r.duplicates_skipped} 条\n隔离记录：${r.quarantined} 条\n下载音频：${r.audio_downloaded} 条\n\n词条已进入查词页；审核标记与录音不会被凭空补全。`;await refresh();await search();notice('导入完成，可到查词页查看。');
}catch(e){notice(e.message);}finally{busy=false;controls();}};
window.addEventListener('pagehide',()=>{if(stream)stream.getTracks().forEach(t=>t.stop());});
api('/api/status').then(async d=>{unlocked=d.authenticated;$('connection').textContent=unlocked?'已登录现有项目':'服务已连接，请用原访问码解锁';if(unlocked){await refresh();await search();await refreshSamples();}controls();}).catch(e=>notice(e.message));
controls();
