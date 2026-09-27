"""Idempotent local installer. Never modifies .env, credentials, databases or recordings."""
from pathlib import Path
import shutil,sys
ROOT=Path(__file__).resolve().parent

def patch(path,old,new,marker):
    body=path.read_text(encoding='utf-8-sig')
    if marker in body:return False
    if body.count(old)!=1:raise ValueError(f'{path.name} 版本不匹配，没有改写。')
    backup=path.with_name(path.name+'.before-corpus.bak')
    if not backup.exists():shutil.copy2(path,backup)
    path.write_text(body.replace(old,new),encoding='utf-8')
    return True

def main():
    if not (ROOT/'corpus_lab/routes.py').is_file():raise ValueError('请把完整 corpus_lab 文件夹放到 app.py 同一层。')
    entry=ROOT/'app.py'
    if not entry.is_file():raise ValueError('请把 install_corpus.py 放在现有项目 app.py 同一级。')
    changed=patch(entry,'    return app\n','    from corpus_lab.routes import mount\n    mount(app, ROOT)\n    return app\n','from corpus_lab.routes import mount')
    page=ROOT/'public/index.html'
    if page.is_file():
        body=page.read_text(encoding='utf-8-sig')
        if 'href="/corpus"' not in body and '</header>' in body:
            backup=page.with_name(page.name+'.before-corpus.bak')
            if not backup.exists():shutil.copy2(page,backup)
            page.write_text(body.replace('</header>','<a href="/corpus">语料工作台 ↗</a></header>',1),encoding='utf-8')
    # Also mount into a previously downloaded audio_first/server.py, when present.
    af=ROOT/'audio_first/server.py'
    if af.is_file():
        old='    return app\n'
        new='    import sys\n    sys.path.insert(0, str(HERE.parent))\n    from corpus_lab.routes import mount\n    mount(app, HERE.parent, HERE.parent / "data" / "corpus_lab")\n    return app\n'
        try:patch(af,old,new,'from corpus_lab.routes import mount')
        except ValueError:print('旧 audio_first 入口版本不同，保留未修改。8787 入口已接入。')
    for name in ('.gitignore','.vercelignore','.dockerignore'):
        target=ROOT/name
        if target.exists():
            b=target.read_text(encoding='utf-8')
            for pattern in ('*.before-corpus.bak','audio_first/.private/','data/'):
                if pattern not in b.splitlines():b+='\n'+pattern+'\n'
            target.write_text(b,encoding='utf-8')
    print('已接入现有项目（重复运行安全）。.env 和原始语料未改动。')
    print('启动原命令：python app.py → http://localhost:8787/corpus')
    print('Cloudflare：关闭旧进程后 python scripts/share_local.py → 公网地址/corpus')
    print('首次打开自动载入 5 条字词参考；当前没有内置真人录音。')

if __name__=='__main__':
    try:main()
    except (OSError,ValueError) as e:print('安装未完成：',e);sys.exit(1)
