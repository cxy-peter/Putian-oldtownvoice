"""Import a user's local key CSV into ignored .env. Never uploads credentials."""
import csv
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def configure():
    path = Path(sys.argv[1].strip('"')) if len(sys.argv) > 1 else None
    if path:
        with path.open(encoding="utf-8-sig", newline="") as f:
            values = [v.strip() for row in csv.reader(f) for v in row]
        keys = [v for v in values if re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", v)]
        if len(keys) != 1:
            raise ValueError("CSV 中必须恰好有一个 API Key。")
        key = keys[0]
    else:
        key = getpass.getpass("百炼北京地域 API Key（不会显示）: ").strip()
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", key):
        raise ValueError("API Key 格式不正确。")
    destination = ROOT / ".env"
    if destination.exists() and input(".env 已存在，覆盖？输入 YES: ") != "YES":
        raise ValueError("保留了现有配置。")
    code = secrets.token_urlsafe(24)
    body = f"DASHSCOPE_API_KEY={key}\nAPP_ACCESS_CODE={code}\nDASHSCOPE_WORKSPACE_ID=\nPUBLIC_ORIGIN=\nHOST=127.0.0.1\nPORT=8787\nDATA_DIR=./data\nMAX_DAILY_AUDIO_SECONDS=1800\n"
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    print("已写入仅服务端使用的 .env。不要提交或共享它。")
    print("网页应用访问码（不是 API Key）:", code)
    print("启动: python app.py → http://localhost:8787")

if __name__ == "__main__":
    try:
        configure()
    except (ValueError, OSError) as e:
        print("配置未完成:", str(e))
        sys.exit(1)
