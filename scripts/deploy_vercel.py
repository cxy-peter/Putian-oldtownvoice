"""Deploy only this app using the user's authenticated official Vercel CLI.
Secrets go through stdin to sensitive environment variables, never CLI arguments.
Requires: npm install -g vercel, and Python 3.12+. Does not buy domains/servers.
"""
import argparse
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from credentials import read_credentials, valid_key

ROOT = Path(__file__).resolve().parents[1]


def read_env():
    result = {}
    paths = [ROOT / 'deployment-private' / 'vercel.env', ROOT / '.env']
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                name, value = line.split('=', 1)
                result[name.strip()] = value.strip().strip('\"').strip("'")
    return result


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(value)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--csv', help='Original private API key CSV; never uploaded')
    p.add_argument('--scope', default='cxy-peters-projects')
    args = p.parse_args()
    vc = shutil.which('vercel')
    if not vc:
        raise ValueError('请先运行 npm install -g vercel，再重试。')
    values = read_env()
    if args.csv:
        values.update(read_credentials(args.csv))
    if not valid_key(values.get('DASHSCOPE_API_KEY', '')):
        raise ValueError('请使用 --csv 指定原密钥 CSV，或先配置本地 .env。')
    # Preserve valid existing access codes; old short codes cannot be used online.
    if len(values.get('APP_ACCESS_CODE', '')) < 24:
        values['APP_ACCESS_CODE'] = secrets.token_urlsafe(24)
    values.setdefault('SESSION_SECRET', '')
    if not values['SESSION_SECRET']:
        values['SESSION_SECRET'] = secrets.token_urlsafe(32)
    private = ROOT / 'deployment-private'
    write_private(private / 'app-access-code.txt', values['APP_ACCESS_CODE'] + '\n')
    write_private(private / 'vercel.env', '\n'.join(k+'='+values[k] for k in ('DASHSCOPE_API_KEY','APP_ACCESS_CODE','SESSION_SECRET','DASHSCOPE_WORKSPACE_ID','ALLOWED_ORIGINS') if k in values)+'\n')
    # Do not print captured environment-command output: providers may echo values.
    def run(parts, secret=None, required=True):
        command = [vc, *parts]
        if secret is not None:
            r = subprocess.run(command, cwd=ROOT, input=secret, text=True, capture_output=True)
        else:
            r = subprocess.run(command, cwd=ROOT)
        if required and r.returncode:
            raise ValueError('Vercel 操作未完成，请检查终端/控制台状态。未输出秘密字段。')
        return r.returncode
    check = subprocess.run([vc,'whoami'], cwd=ROOT, capture_output=True)
    if check.returncode:
        run(['login'])
    scope = ['--scope', args.scope]
    run(['link','--yes','--project','putian-oldtownvoice',*scope])
    for name in ('DASHSCOPE_API_KEY','APP_ACCESS_CODE','SESSION_SECRET'):
        run(['env','add',name,'production','--sensitive','--force',*scope], values[name])
    for name in ('DASHSCOPE_WORKSPACE_ID','ALLOWED_ORIGINS'):
        if values.get(name):
            run(['env','add',name,'production','--force',*scope], values[name])
    # Never upload old local-tunnel PUBLIC_ORIGIN or DATA_DIR to the cloud.
    if (ROOT / '.git').exists():
        result = run(['git','connect','--yes',*scope], required=False)
        if result:
            print('Git 自动部署未连接；本次仍可部署。请在项目 Settings → Git 连接指定仓库。')
    run(['deploy','--prod','--yes',*scope])
    print('请打开 Vercel 返回的生产地址。访问码已保存：deployment-private/app-access-code.txt')
    print('尚需实测 WebSocket、百炼接口、莆仙话识别与国内网络；部署成功不等于这些测试通过。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyboardInterrupt) as e:
        print('部署停止：', str(e) if not isinstance(e, KeyboardInterrupt) else '已取消')
        raise SystemExit(1)
