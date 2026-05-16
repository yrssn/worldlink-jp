"""统一 CSV 导出工具。

- 自动加 UTF-8 BOM，避免 Excel 打开乱码
- 支持嵌套字段（点路径，如 ``pageAdLibrary.id``）
- 支持自定义 getter（callable，传 row 返回值）
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Callable, Iterable, Sequence, Union
from urllib.parse import quote

from fastapi import Response

ColumnGetter = Union[str, Callable[[Any], Any]]
"""字段路径字符串（支持 ``a.b.c``）或一个 callable。"""


def _resolve(row: Any, getter: ColumnGetter) -> Any:
    if callable(getter):
        try:
            return getter(row)
        except Exception:
            return ""

    # 支持 dict / orm 对象 / 嵌套
    current: Any = row
    for part in str(getter).split("."):
        if current is None:
            return ""
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(v) for v in value if v is not None)
    if isinstance(value, dict):
        # 字典统一 JSON 化，避免 csv 里冒充列
        import json
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def build_csv(
    rows: Iterable[Any],
    columns: Sequence[tuple[str, ColumnGetter]],
) -> bytes:
    """生成带 BOM 的 UTF-8 CSV bytes。

    columns: [(列名, 字段路径或 getter), ...]
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([h for h, _ in columns])
    for row in rows:
        writer.writerow([_to_cell(_resolve(row, g)) for _, g in columns])
    data = buf.getvalue().encode("utf-8-sig")
    return data


def csv_response(filename: str, data: bytes) -> Response:
    """返回 CSV Response，带 RFC 5987 形式的文件名（兼容中文）。"""
    safe_ascii = "".join(c if ord(c) < 128 else "_" for c in filename)
    quoted = quote(filename)
    disposition = (
        f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{quoted}"
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )
