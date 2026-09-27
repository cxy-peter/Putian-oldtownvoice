"""Configure local .env from an Alibaba Cloud Bailian CSV.

Simplest usage:
    python scripts/setup.py

Put the exported *.csv anywhere in the repository root. The script will
auto-detect it. You can still pass an explicit path if you prefer:
    python scripts/setup.py "my-export.csv"
"""
import getpass
import os
import secrets
import sys
from pathlib import Path

from credentials import read_credentials, valid_key

ROOT = Path(__file__).resolve().parents[1]


def _auto_find_csv():
    candidates = []
    errors = []
    for path in sorted(ROOT.glob("*.csv")):
        try:
            values = read_credentials(path)
            candidates.append((path, values))
        except (ValueError, OSError) as exc:
            errors.append((path, str(exc)))

    if len(candidates) == 1:
        path, values = candidates[0]
        print(f"自动识别百炼凭据文件：{path.name}")
        return path, values

    if len(candidates) > 1:
        print("发现多个可用的百炼 CSV：")
        for i, (path, _) in enumerate(candidates, 1):
            print(f"  {i}. {path.name}")
        answer = input("请输入要使用的序号: ").strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(candidates):
            raise ValueError("没有选择有效的 CSV。")
        return candidates[int(answer) - 1]

    if list(ROOT.glob("*.csv")):
        detail = "; ".join(f"{p.name}: {msg}" for p, msg in errors[:3])
        raise ValueError("找到了 CSV，但没有识别到可用的百炼凭据。" + (f" {detail}" if detail else ""))

    return None, None


def _load_values():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1].strip('"')).expanduser()
        if not path.is_absolute():
            # First interpret relative paths from the current shell, then from repo root.
            cwd_path = Path.cwd() / path
            root_path = ROOT / path
            path = cwd_path if cwd_path.exists() else root_path
        values = read_credentials(path)
        print(f"已读取百炼凭据文件：{path.name}")
        return values

    _, values = _auto_find_csv()
    if values:
        return values

    print("项目根目录没有找到百炼 CSV，将改为手动输入 API Key。")
    return {
        "DASHSCOPE_API_KEY": getpass.getpass(
            "百炼华北2（北京）API Key（输入不会显示）: "
        ).strip()
    }


def configure():
    values = _load_values()
    key = values["DASHSCOPE_API_KEY"]
    workspace = values.get("DASHSCOPE_WORKSPACE_ID", "")

    if not valid_key(key):
        raise ValueError("API Key 格式不正确。")

    destination = ROOT / ".env"
    if destination.exists():
        answer = input(".env 已存在。输入 YES 才覆盖，否则保留现有配置: ").strip()
        if answer != "YES":
            print("保留现有 .env，未作修改。")
            return

    code = secrets.token_urlsafe(24)
    body = (
        f"DASHSCOPE_API_KEY={key}\n"
        f"APP_ACCESS_CODE={code}\n"
        f"DASHSCOPE_WORKSPACE_ID={workspace}\n"
        "PUBLIC_ORIGIN=\n"
        "HOST=127.0.0.1\n"
        "PORT=8787\n"
        "DATA_DIR=./data\n"
        "MAX_DAILY_AUDIO_SECONDS=1800\n"
    )

    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)

    print("配置完成：已写入仅服务端使用的 .env。不要提交或共享它。")
    if workspace:
        print(f"已识别业务空间：{workspace}")
    else:
        print("未从 CSV 读取 workspaceId；使用默认 DashScope 接入方式。")
    print("网页应用访问码（不是 API Key）:", code)
    print("本地启动：python app.py")
    print("浏览器打开：http://localhost:8787")


if __name__ == "__main__":
    try:
        configure()
    except (ValueError, OSError, csv.Error if False else ValueError) as e:
        # Keep the message credential-free.
        print("配置未完成:", str(e))
        sys.exit(1)
