// Deterministic sample conversion test, not a real microphone test.
const {readFileSync}=require('node:fs'),{runInNewContext}=require('node:vm'),assert=require('node:assert/strict');
for(const rate of [16000,44100,48000]){
  let Processor,events=[];
  const context={sampleRate:rate,AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>events.push(m)}}},registerProcessor:(n,p)=>Processor=p,Int16Array,Math};
  runInNewContext(readFileSync('public/capture.js','utf8'),context);
  const p=new Processor();let left=rate;
  while(left){const size=Math.min(128,left);p.process([[new Float32Array(size).fill(.25),new Float32Array(size).fill(.75)]]);left-=size;}
  p.port.onmessage({data:'stop'});const audio=events.filter(x=>x.pcm).map(x=>new Int16Array(x.pcm));
  assert.equal(audio.reduce((n,a)=>n+a.length,0),16000);
  assert.ok(audio.every(a=>a.every(v=>Math.abs(v-16384)<=1)));assert.equal(events.at(-1).flushed,true);assert.equal(p.process([]),false);
}
console.log('3 sample rates passed: continuous resampling, stereo downmix, PCM amplitude, flush and stop');
