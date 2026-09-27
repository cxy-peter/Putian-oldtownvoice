"""Read private DashScope exports without assuming a particular token prefix.
Never trust an uploaded apiHost as an arbitrary destination; endpoints stay fixed.
"""
import csv
import re
from pathlib import Path


def valid_key(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.~+/=-]{20,512}", value))


def read_credentials(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = [[cell.strip() for cell in row] for row in csv.reader(f)]
    candidates = []
    fields = {}
    for row in rows:
        if len(row) == 2:
            name = re.sub(r"[ _-]", "", row[0]).lower()
            if name in ("apikey", "workspaceid", "apihost"):
                if name in fields:
                    raise ValueError("CSV 包含重复的凭据字段。")
                fields[name] = row[1]
    if "apikey" in fields:
        candidates = [fields["apikey"]]
    elif rows:
        header = [re.sub(r"[ _-]", "", c).lower() for c in rows[0]]
        if "apikey" in header:
            i = header.index("apikey")
            candidates = [row[i] for row in rows[1:] if len(row) > i and row[i]]
        else:
            candidates = [c for row in rows for c in row if re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", c)]
    if len(candidates) != 1 or not valid_key(candidates[0]):
        raise ValueError("CSV 必须包含唯一且非空的 apiKey 字段；不要使用已掩码的导出。")
    result = {"DASHSCOPE_API_KEY": candidates[0]}
    workspace = fields.get("workspaceid", "")
    if workspace:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace):
            raise ValueError("业务空间 ID 格式无效。")
        host = fields.get("apihost", "").removeprefix("https://").rstrip("/")
        expected = workspace + ".cn-beijing.maas.aliyuncs.com"
        if host and host != expected:
            raise ValueError("CSV 不是预期的北京业务空间接口；请核对地域，不会连接未知主机。")
        result["DASHSCOPE_WORKSPACE_ID"] = workspace
    return result
