"""Import a user's local key CSV into ignored .env. Never uploads credentials."""
import getpass
import os
import secrets
import sys
from pathlib import Path
from credentials import read_credentials, valid_key

ROOT = Path(__file__).resolve().parents[1]

def configure():
    path = Path(sys.argv[1].strip('"')) if len(sys.argv) > 1 else None
    values = read_credentials(path) if path else {"DASHSCOPE_API_KEY": getpass.getpass("百炼北京地域 API Key（不会显示）: ").strip()}
    key = values["DASHSCOPE_API_KEY"]
    workspace = values.get("DASHSCOPE_WORKSPACE_ID", "")
    if not valid_key(key):
        raise ValueError("API Key 格式不正确。")
    destination = ROOT / ".env"
    if destination.exists() and input(".env 已存在，覆盖？输入 YES: ") != "YES":
        raise ValueError("保留了现有配置。")
    code = secrets.token_urlsafe(24)
    body = f"DASHSCOPE_API_KEY={key}\nAPP_ACCESS_CODE={code}\nDASHSCOPE_WORKSPACE_ID={workspace}\nPUBLIC_ORIGIN=\nHOST=127.0.0.1\nPORT=8787\nDATA_DIR=./data\nMAX_DAILY_AUDIO_SECONDS=1800\n"
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
