# -*- coding: utf-8 -*-
"""office/表格结构化直写（T4，reference_af 拆解卡）。

对齐 Agent-S 的 ``set_cell_values``（gui_agents/s3/agents/grounding.py:51-176，
LibreOffice UNO 直写单元格）能力——本仓走**文件级直写 + 写后回读校验**两段式：
openpyxl（xlsx/xlsm）/csv 标准库直写，绕开逐格 GUI 点击；写完重新读取逐格
比对，回读不一致如实报 ``mismatch``（不冒充写成功）。

边界：
- 值类型推断对齐对方语义：整数/浮点/公式（``=`` 开头原样）/字符串；
- 单元格引用格式 ``A1``（列字母+行号，1 起始）；
- openpyxl 惰性 import（可选依赖缺席如实结构化报错，不装包）；
- csv 用标准库（无外部依赖）。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = ["editWorkbookCells"]

#: 合法单元格引用：列字母（1-3 位）+ 行号（1 起始，无前导零）。
_CELL_REF = re.compile(r"^[A-Za-z]{1,3}[1-9][0-9]*$")

#: 支持的扩展名（docx 按拆解卡边界"次之"另批）。
_SUPPORTED_SUFFIXES = (".xlsx", ".xlsm", ".csv")


def _loadOpenpyxl():
    """openpyxl 惰性装载（测试可注入缺席场景）。"""
    import openpyxl

    return openpyxl


def _coerceValue(text: Any) -> Any:
    """单元格值类型推断：公式（=开头）原样；整数/浮点转数值；其余字符串。"""
    s = str(text)
    if s.startswith("="):
        return s
    try:
        return int(s)
    except (TypeError, ValueError):
        pass
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    return s


def _cellRefToRowCol(ref: str) -> Tuple[int, int]:
    """``A1`` → (row, col)（1 起始；调用方已过 _CELL_REF 正则）。"""
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    digits = "".join(ch for ch in ref if ch.isdigit())
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(digits), col


def _editCsv(target: Path, cellValues: Dict[str, Any]) -> Dict[str, Any]:
    """csv 直写：按引用定位 (row, col)，必要时扩行/扩列，写后回读比对。"""
    with target.open("r", encoding="utf-8", newline="") as f:
        rows: List[List[str]] = [list(row) for row in csv.reader(f)]
    parsed: List[Tuple[str, int, int, Any]] = []
    for ref, value in cellValues.items():
        if not _CELL_REF.match(str(ref)):
            return {
                "success": False,
                "error": f"非法单元格引用: {ref}（格式如 A1）",
            }
        row, col = _cellRefToRowCol(str(ref))
        parsed.append((str(ref), row, col, _coerceValue(value)))
        while len(rows) < row:
            rows.append([])
        for rowItems in rows:
            while len(rowItems) < col:
                rowItems.append("")
        rows[row - 1][col - 1] = str(value)
    with target.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    # 回读校验
    with target.open("r", encoding="utf-8", newline="") as f:
        rows2 = [list(row) for row in csv.reader(f)]
    readback: Dict[str, Any] = {}
    mismatch: List[Dict[str, Any]] = []
    for ref, row, col, value in parsed:
        got = rows2[row - 1][col - 1]
        readback[ref] = got
        if got != str(value):
            mismatch.append({"ref": ref, "expected": str(value), "got": got})
    return {
        "success": not mismatch,
        "file_path": str(target),
        "written": len(parsed),
        "readback": readback,
        "mismatch": mismatch,
    }


def editWorkbookCells(
    path: Any,
    cellValues: Dict[str, Any],
    sheetName: Optional[str] = None,
) -> Dict[str, Any]:
    """结构化直写单元格并**写后回读校验**。

    Args:
        path: xlsx/xlsm/csv 文件路径（须已存在；创建新文件走 file_create）。
        cellValues: ``{"A1": "值", ...}``；值按 整数/浮点/公式/字符串 推断。
        sheetName: 工作表名（xlsx；缺省活动表）。

    Returns:
        成功：``{"success": True, "file_path", "sheet", "written", "readback",
        "mismatch": []}``；失败：``{"success": False, "error": ...}``（含
        openpyxl 缺席/文件不存在/非法引用/不支持扩展名/工作表不存在/回读不一致）。
    """
    target = Path(str(path or ""))
    if not target.exists():
        return {"success": False, "error": f"文件不存在: {target}"}
    suffix = target.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        return {
            "success": False,
            "error": f"不支持的扩展名 {target.suffix}（支持 {'/'.join(_SUPPORTED_SUFFIXES)}）",
        }
    if not cellValues:
        return {"success": False, "error": "cell_values 必须非空"}
    if suffix == ".csv":
        return _editCsv(target, cellValues)

    try:
        openpyxl = _loadOpenpyxl()
    except ImportError as exc:
        return {"success": False, "error": f"openpyxl 未安装: {exc}"}

    badRefs = [ref for ref in cellValues if not _CELL_REF.match(str(ref))]
    if badRefs:
        return {
            "success": False,
            "error": f"非法单元格引用: {badRefs[:5]}（格式如 A1）",
        }

    wb = openpyxl.load_workbook(str(target))
    if sheetName:
        if sheetName not in wb.sheetnames:
            return {
                "success": False,
                "error": f"工作表不存在: {sheetName}（现有 {wb.sheetnames}）",
            }
        ws = wb[sheetName]
    else:
        ws = wb.active
    for ref, value in cellValues.items():
        ws[str(ref)] = _coerceValue(value)
    wb.save(str(target))

    # 写后回读校验：重新加载落盘文件逐格比对（不比对内存态）
    wb2 = openpyxl.load_workbook(str(target))
    ws2 = wb2[sheetName] if sheetName else wb2.active
    readback: Dict[str, Any] = {}
    mismatch: List[Dict[str, Any]] = []
    for ref, value in cellValues.items():
        expected = _coerceValue(value)
        got = ws2[str(ref)].value
        readback[str(ref)] = got
        if got != expected:
            mismatch.append({"ref": str(ref), "expected": expected, "got": got})
    return {
        "success": not mismatch,
        "file_path": str(target),
        "sheet": ws.title,
        "written": len(cellValues),
        "readback": readback,
        "mismatch": mismatch,
    }
