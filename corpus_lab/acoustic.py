"""Experimental short-phrase MFCC/DTW retrieval, NOT an ASR or calibrated matcher.
No model weights or network. Requires numpy only when this optional feature is used.
"""
import io, math, wave

def features(wav):
    try: import numpy as np
    except ImportError as e: raise ValueError('本地声音检索需安装 numpy：python -m pip install numpy') from e
    with wave.open(io.BytesIO(wav),'rb') as w:
        x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float64)/32768
    # Preserve the complete recording; only feature frames are subsampled to cap cost.
    x=np.concatenate((x[:1],x[1:]-.97*x[:-1]))
    nfft,window,hop=512,400,160
    if len(x)<window:x=np.pad(x,(0,window-len(x)))
    frames=np.lib.stride_tricks.sliding_window_view(x,window)[::hop].copy()
    energy=np.mean(frames**2,axis=1)
    # Remove near-silence frames, never synthesize missing speech.
    frames=frames[energy>max(float(energy.max())*.002,1e-9)]
    if len(frames)<3:raise ValueError('可用语音太短，请重新录制完整短句。')
    power=np.abs(np.fft.rfft(frames*np.hamming(window),nfft))**2/nfft
    mel=np.linspace(0,2595*np.log10(1+8000/700),28)
    bins=np.floor((nfft+1)*(700*(10**(mel/2595)-1))/16000).astype(int)
    bank=np.zeros((26,nfft//2+1))
    for i in range(26):
        a,b,c=bins[i:i+3]
        for k in range(a,b):bank[i,k]=(k-a)/max(b-a,1)
        for k in range(b,c):bank[i,k]=(c-k)/max(c-b,1)
    logs=np.log(np.maximum(power@bank.T,1e-10))
    dct=np.cos(np.pi/26*(np.arange(26)+.5)[None,:]*np.arange(1,14)[:,None])
    mfcc=logs@dct.T
    mfcc=(mfcc-mfcc.mean(axis=0))/np.maximum(mfcc.std(axis=0),.5)
    return mfcc[::max(1,math.ceil(len(mfcc)/100))]

def distance(a,b):
    import numpy as np
    cost=np.sqrt(np.mean((a[:,None,:]-b[None,:,:])**2,axis=2))
    n,m=cost.shape
    prev=np.full(m+1,np.inf);prev[0]=0
    # Sloped band allows differing speaking rates, but is deliberately a baseline.
    for i in range(n):
        curr=np.full(m+1,np.inf)
        for j in range(m):
            if abs(i/max(n-1,1)-j/max(m-1,1))>.3: continue
            curr[j+1]=cost[i,j]+min(prev[j+1],curr[j],prev[j])
        prev=curr
    score=float(prev[-1]/(n+m))
    return score if math.isfinite(score) else 1e6

def retrieve(audio,info,records,folder):
    query=features(audio);eligible=[];identical=0
    for r in records:
        if not r.get('allow_reference') or r.get('split') in ('dev','test'): continue
        if r['audio']['sha256']==info['sha256']:
            identical+=1;continue
        eligible.append(r)
    # Bounded MVP, explicitly report any reference cap. Do not load URLs from metadata.
    scored=[]
    for r in eligible[:80]:
        try:score=distance(query,features((folder/r['audio_path']).read_bytes()))
        except (ValueError,OSError):continue
        scored.append({'id':r['id'],'mandarin':r['mandarin'],'district':r['district'],
            'speaker_id':r['speaker_id'],'distance':round(score,4),
            'audio_path':'/api/lab/audio/'+r['id'],'kind':'candidate_not_translation'})
    scored.sort(key=lambda r:r['distance'])
    return {'matches':scored[:3],'eligible':len(eligible),'compared':len(scored),'identical_excluded':identical,
        'method':'MFCC + DTW / unvalidated short-phrase baseline','calibrated':False,
        'message':'相似距离不是准确率；可能所有候选都不正确，请回听参考录音。' if scored else
                  '没有可比较的参考录音。先补录并审核、允许本机检索；同一文件与 dev/test 不参与。'}
