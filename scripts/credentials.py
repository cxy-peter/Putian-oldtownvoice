"""Read private Alibaba Cloud Model Studio credential exports safely.

Supports the two-column CSV exported by Bailian, for example:
    id,7471092
    apiKey,sk-...
    apiHost,ws-....cn-beijing.maas.aliyuncs.com
    workspaceId,ws-...

The parser also accepts a normal header-row CSV with an apiKey column.
Credentials are never uploaded by this module.
"""
import csv
import re
from pathlib import Path


def _name(value):
    return re.sub(r"[\\s_-]+", "", (value or "").replace("\ufeff", "")).lower()


def valid_key(value):
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9_.~+/=-]{20,512}", value.strip())
    )


def _one_value(values, label):
    """Allow the same exported value to appear more than once, reject conflicts."""
    unique = []
    for value in values:
        value = (value or "").strip().strip('"').strip("'")
        if value and value not in unique:
            unique.append(value)
    if not unique:
        return ""
    if len(unique) > 1:
        raise ValueError(f"CSV 中发现多个不同的 {label}，请只保留同一个业务空间的导出。")
    return unique[0]


def read_credentials(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"找不到 CSV：{path}")

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [[cell.strip() for cell in row] for row in csv.reader(f)]

    if not rows:
        raise ValueError("CSV 是空文件。")

    # 1) Bailian's current two-column key/value export.
    field_values = {}
    for row in rows:
        if len(row) < 2:
            continue
        key = _name(row[0])
        if key in {"apikey", "workspaceid", "apihost"}:
            field_values.setdefault(key, []).append(row[1])

    api_key = _one_value(field_values.get("apikey", []), "apiKey")
    workspace = _one_value(field_values.get("workspaceid", []), "workspaceId")
    api_host = _one_value(field_values.get("apihost", []), "apiHost")

    # 2) Also accept a regular header-row CSV.
    if not api_key:
        header = [_name(cell) for cell in rows[0]]
        if "apikey" in header:
            idx = header.index("apikey")
            api_key = _one_value(
                [row[idx] for row in rows[1:] if len(row) > idx],
                "apiKey",
            )

    if not api_key:
        raise ValueError(
            "没有找到 apiKey。请使用百炼控制台导出的原始 CSV；"
            "支持两列格式（apiKey,值）或带 apiKey 表头的 CSV。"
        )
    if not valid_key(api_key):
        raise ValueError(
            "已找到 apiKey 字段，但值看起来无效或已被掩码。"
            "请重新从百炼导出完整 API Key。"
        )

    result = {"DASHSCOPE_API_KEY": api_key}

    if workspace:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace):
            raise ValueError("workspaceId 格式无效。")
        # Never trust a CSV host as an arbitrary destination. We only validate
        # that an exported host, if present, matches the Beijing workspace.
        if api_host:
            host = api_host.removeprefix("https://").removeprefix("wss://").rstrip("/")
            expected = workspace + ".cn-beijing.maas.aliyuncs.com"
            if host != expected:
                raise ValueError(
                    "CSV 的 apiHost 与 workspaceId 不匹配，或不是华北2（北京）业务空间。"
                )
        result["DASHSCOPE_WORKSPACE_ID"] = workspace

    return result
