"""Export validated private corpus to Fun-ASR wav.scp/text inputs; does NOT train.
python scripts/prepare_training.py unpacked_private_export output_directory
Then use official QwenAudio/Fun-ASR tools/scp2jsonl.py to compute real lengths.
"""
import hashlib,json,re,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import inspect_wav

def prepare(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if any(c.isspace() for c in str(destination)):
        raise ValueError('Output path must not contain whitespace for SCP compatibility')
    rows=[json.loads(line) for line in (source/'manifest.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    groups={};seen=set();clean=[]
    for row in rows:
        if row.get('reviewed') is not True or row.get('consent') is not True:raise ValueError('Unreviewed or unconsented sample')
        split=row['split'];speaker=row['speaker'];ident=row['id']
        if split not in ('train','dev','test') or not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid split or ID')
        if speaker in groups and groups[speaker]!=split:raise ValueError('Speaker leakage')
        groups[speaker]=split
        path=(source/row['audio']).resolve()
        if not path.is_relative_to(source):raise ValueError('Unsafe audio path')
        raw=path.read_bytes();inspect_wav(raw);digest=hashlib.sha256(raw).hexdigest()
        if digest!=row['audio_sha256'] or digest in seen:raise ValueError('Audio hash mismatch or duplicate')
        seen.add(digest)
        reference=' '.join(row['reference'].split())
        if not reference:raise ValueError('Missing human transcript')
        clean.append((split,ident,path,reference))
    if not clean:raise ValueError('No reviewed audio; no training data created')
    if destination.exists() and any(destination.iterdir()):raise ValueError('Destination must be empty')
    (destination/'audio').mkdir(parents=True,exist_ok=True)
    report={}
    for split in ('train','dev','test'):
        scp=[];texts=[]
        for group,ident,path,reference in clean:
            if group!=split:continue
            target=destination/'audio'/f'{ident}.wav';shutil.copyfile(path,target)
            scp.append(f'{ident} {target}');texts.append(f'{ident} {reference}')
        (destination/f'{split}_wav.scp').write_text('\n'.join(scp)+'\n',encoding='utf-8')
        (destination/f'{split}_text.txt').write_text('\n'.join(texts)+'\n',encoding='utf-8');report[split]=len(scp)
    (destination/'README.txt').write_text('Private data. Not trained. Run official scp2jsonl.py for fbank/token lengths. Never train or prompt on test speakers.\n')
    return report
if __name__=='__main__':
    print(json.dumps(prepare(sys.argv[1],sys.argv[2]),ensure_ascii=False))
