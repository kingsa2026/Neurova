"""文件行源连接器（立项方案批 C1，2026-11-07 裁定 §2.3-1A）。

CSV/TSV/JSON/JSONL 四格式一份适配器类按 `format` 分派读取器——不写四套类。
一行源行＝描述符 columns 的一行，与 `applyMapping` 的输入形状天然同构。

纪律（方案 §4 原文有效）：
- 逐行流式读（csv/jsonl 迭代器），不整文件载入内存；json（数组）是唯一例外，
  C1 如实标注；
- 游标＝文件指纹＋行偏移：指纹变了从 0 重读（幂等由咽喉内容键兜底），
  指纹没变按偏移推进；
- 只承诺 utf-8/utf-8-sig（方案 §2.2 候选 1 的编码边界），解码失败显式 error
  不吞成空批；
- 无第三方依赖（stdlib csv/json/hashlib）。
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .protocols import ChangeBatch, SourceCursor, SourceHealth, SourceSchema


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:32]


def _cursorToken(fingerprint: str, offset: int) -> str:
    return "fp=%s:off=%d" % (fingerprint, offset)


class FileRowAdapter:
    """`sourceType=file` 的 Protocol 实现（fetchBatch 是 async 契约，读文件本身同步）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._format = str(descriptor.get("format") or "")
        self._path = Path(str(descriptor.get("path") or ""))

    # ── Protocol 四动词 ──────────────────────────────────────

    async def describeSchema(self) -> SourceSchema:
        rows, columns = self._readHeader()
        return SourceSchema(
            sourceId=self._sourceId, sourceType="file",
            tables=[{"name": self._path.name, "columns": columns,
                     "rows_hint": len(rows) if rows is not None else None}],
        )

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        fingerprint = _fingerprint(self._path)
        offset = 0
        if cursor is not None and not cursor.isEmpty():
            token = str(cursor.token)
            if "fp=" in token and token.split("fp=")[1].split(":")[0] == fingerprint:
                try:
                    offset = int(token.rsplit("off=", 1)[1])
                except (IndexError, ValueError):
                    offset = 0
        rows, _ = self._readRows(offset, max(1, int(limit)))
        nextOffset = offset + len(rows)
        hasMore = nextOffset < self._countRows()
        nextCursor = SourceCursor(_cursorToken(fingerprint, nextOffset)) if rows or hasMore else None
        return ChangeBatch(
            rows=rows,
            nextCursor=nextCursor,
            hasMore=hasMore,
            fetchedAt="",
        )

    async def health(self) -> SourceHealth:
        if not self._path.exists():
            return SourceHealth(status="error",
                                reason="path 不存在: %s" % self._path)
        try:
            with self._path.open("r", encoding="utf-8-sig") as handle:
                handle.read(1)
        except (OSError, UnicodeDecodeError) as exc:
            return SourceHealth(status="error",
                                reason="path 不可读或非 utf-8 编码: %s" % exc)
        return SourceHealth(status="ok")

    async def close(self) -> None:
        return None

    # ── 读取器（按 format 分派，四格式不写四套类）────────────

    def _open(self):
        return self._path.open("r", encoding="utf-8-sig", newline="")

    def _readHeader(self) -> tuple:
        """(rows 或 None, columns)：流式格式只读头；json 数组如实全载（C1 边界）。"""
        if self._format in ("csv", "tsv"):
            with self._open() as handle:
                reader = csv.reader(handle, delimiter="\t" if self._format == "tsv" else ",")
                header = next(reader, [])
            return None, [c.strip() for c in header]
        if self._format == "jsonl":
            with self._open() as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        obj = json.loads(line)
                        return None, list(obj.keys())
            return None, []
        if self._format == "json":
            with self._open() as handle:
                data = json.load(handle)
            rows = data if isinstance(data, list) else [data]
            return rows, list(rows[0].keys()) if rows else []
        raise ValueError("file.format %r 不在闭集（csv/tsv/json/jsonl）" % self._format)

    def _readRows(self, offset: int, limit: int) -> tuple:
        """从 offset 起最多 limit 行；返回 (行 dicts, columns)。"""
        rows: List[Dict[str, Any]] = []
        if self._format in ("csv", "tsv"):
            with self._open() as handle:
                reader = csv.reader(handle, delimiter="\t" if self._format == "tsv" else ",")
                header = [c.strip() for c in next(reader, [])]
                for index, record in enumerate(reader):
                    if index < offset:
                        continue
                    if len(rows) >= limit:
                        break
                    rows.append({header[i]: (record[i] if i < len(record) else "")
                                 for i in range(len(header))})
            return rows, header
        if self._format == "jsonl":
            with self._open() as handle:
                index = 0
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    if index >= offset and len(rows) < limit:
                        rows.append(json.loads(line))
                    index += 1
            return rows, []
        if self._format == "json":
            with self._open() as handle:
                data = json.load(handle)
            allRows = data if isinstance(data, list) else [data]
            return allRows[offset:offset + limit], []
        raise ValueError("file.format %r 不在闭集（csv/tsv/json/jsonl）" % self._format)

    def _countRows(self) -> int:
        if self._format == "json":
            with self._open() as handle:
                data = json.load(handle)
            return len(data if isinstance(data, list) else [data])
        count = 0
        with self._open() as handle:
            if self._format in ("csv", "tsv"):
                reader = csv.reader(handle, delimiter="\t" if self._format == "tsv" else ",")
                next(reader, None)
                count = sum(1 for record in reader if record)
            else:
                count = sum(1 for line in handle if line.strip())
        return count
