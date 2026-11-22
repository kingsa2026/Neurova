"""文件解析四维结构化预算（资源治理 P1-3）。

对齐参照系 ad fileParseBudget 的防线形态：解析前对四个维度做结构化
预算判定，任一超限即抛 `FileParseBudgetError` 快速失败——防恶意/畸形
文件（含压缩炸弹型文档）拖垮解析线程：

1. 输入体积（原始字节，`NEUROVA_PARSE_MAX_INPUT_BYTES`，缺省 64MB）
2. 抽取字符（既有 `attachment_parser.MAX_EXTRACT_CHARS` 单源，本预算
   不另立第二份——抽取侧仍按既有截断语义）
3. 条目数（PDF 页数 `NEUROVA_PARSE_MAX_PAGES`，缺省 2000）
4. 单元格面积（表格 行×列，`NEUROVA_PARSE_MAX_SHEET_ROWS`/
   `NEUROVA_PARSE_MAX_CELL_AREA`，缺省 10 万行 / 500 万格）

上限均于调用时读环境变量（测试可按用例注入小上限）。
"""

from __future__ import annotations

import os

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class FileParseBudgetError(ValueError):
    """解析预算超限（reason ∈ input_too_large/too_many_pages/too_many_rows/cell_area_exceeded）。"""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _envInt(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def maxParseInputBytes() -> int:
    return max(1, _envInt("NEUROVA_PARSE_MAX_INPUT_BYTES", 64 * 1024 * 1024))


def maxParsePages() -> int:
    return max(1, _envInt("NEUROVA_PARSE_MAX_PAGES", 2000))


def maxParseSheetRows() -> int:
    return max(1, _envInt("NEUROVA_PARSE_MAX_SHEET_ROWS", 100_000))


def maxParseCellArea() -> int:
    return max(1, _envInt("NEUROVA_PARSE_MAX_CELL_AREA", 5_000_000))


def assertParseInputBudget(data: bytes, filename: str = "") -> None:
    """输入体积预算：空文件与超限文件快速失败。"""
    data = data or b""
    if not data:
        raise FileParseBudgetError("empty_file", filename)
    cap = maxParseInputBytes()
    if len(data) > cap:
        raise FileParseBudgetError(
            "input_too_large", f"{filename}: {len(data)} bytes > {cap} bytes"
        )


def assertPagesBudget(pageCount: int, filename: str = "") -> None:
    """条目数预算（PDF 页数）。"""
    cap = maxParsePages()
    if int(pageCount) > cap:
        raise FileParseBudgetError("too_many_pages", f"{filename}: {pageCount} > {cap}")


def assertSheetsBudget(sheets, filename: str = "") -> None:
    """表格预算：任一工作表行数超限或 行×列 面积超限即失败。"""
    rowsCap = maxParseSheetRows()
    areaCap = maxParseCellArea()
    for sheet in sheets or []:
        rows = int(sheet.get("rows") or 0)
        cols = int(sheet.get("cols") or 0)
        name = str(sheet.get("name") or "")
        if rows > rowsCap:
            raise FileParseBudgetError(
                "too_many_rows", f"{filename}:{name}: {rows} rows > {rowsCap}"
            )
        area = rows * cols
        if area > areaCap:
            raise FileParseBudgetError(
                "cell_area_exceeded", f"{filename}:{name}: {rows}x{cols}={area} > {areaCap}"
            )
