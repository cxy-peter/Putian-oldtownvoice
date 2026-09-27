/* AudioWorklet: downmix and integrate continuous samples into 16 kHz PCM16.
   No timer-based fake transcript, no per-chunk resampling phase reset. */
class Capture extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer=new Int16Array(1600); this.n=0; this.sum=0; this.used=0;
    this.ratio=sampleRate/16000; this.stopped=false;
    this.port.onmessage=e=>{if(e.data==='stop'){this.stopped=true;this.flush();this.port.postMessage({flushed:true});}};
  }
  flush(){if(this.n){const data=this.buffer.slice(0,this.n);this.port.postMessage({pcm:data.buffer},[data.buffer]);this.n=0;}}
  process(inputs){
    if(this.stopped)return false;
    const channels=inputs[0]; if(!channels?.length)return true;
    let energy=0;
    for(let i=0;i<channels[0].length;i++){
      let value=0;for(const c of channels)value+=c[i]/channels.length;energy+=value*value;
      let remain=1;
      while(remain>1e-8){
        const use=Math.min(remain,this.ratio-this.used);this.sum+=value*use;this.used+=use;remain-=use;
        if(this.used>=this.ratio-1e-8){
          const x=Math.max(-1,Math.min(1,this.sum/this.ratio));this.buffer[this.n++]=Math.round(x*(x<0?32768:32767));
          this.sum=0;this.used=0;if(this.n===1600)this.flush();
        }
      }
    }
    this.port.postMessage({level:Math.sqrt(energy/channels[0].length)});return true;
  }
}
registerProcessor('putian-capture',Capture);
