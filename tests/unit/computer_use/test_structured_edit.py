# -*- coding: utf-8 -*-
"""T4 office/表格结构化直写（reference_af 拆解卡）红灯测试。

契约（拆解评测 §5 卡 T4）：
- `structured_edit.editWorkbookCells`：xlsx/csv 文件级直写单元格 + **写后回读
  校验**（绕开逐格 GUI 点击；对齐对方 set_cell_values 的 UNO 直写思路）；
- 值类型推断：整数/浮点/公式（=开头）/字符串；
- 工具 `computer_doc_edit`：路径经 `_resolve_agent_path` 工作区白名单；执行期
  持 desktop 车道（与 GUI 动作互斥）；登记不可重现名单（写副作用）。
"""

import csv
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.computer_use import structured_edit
from neurova.tool_executor import ToolExecutor


def _makeXlsx(path, rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=value)
    wb.save(str(path))
    return path


class TestEditWorkbookCells:
    def test_xlsx_write_and_readback(self, tmp_path):
        xlsx = _makeXlsx(tmp_path / "book.xlsx", [["a", "b"], ["c", "d"]])
        res = structured_edit.editWorkbookCells(
            xlsx, {"A1": "hello", "B2": "42", "C3": "=SUM(A1:B2)"})
        assert res["success"] is True
        assert res["written"] == 3
        assert res["readback"]["A1"] == "hello"
        assert res["readback"]["B2"] == 42, "数字串应按数值写入"
        assert res["readback"]["C3"] == "=SUM(A1:B2)", "公式串原样写入"
        assert res["mismatch"] == []

    def test_csv_write_and_readback(self, tmp_path):
        target = tmp_path / "data.csv"
        target.write_text("name,qty\napple,1\n", encoding="utf-8")
        res = structured_edit.editWorkbookCells(target, {"B2": "7", "A1": "品名"})
        assert res["success"] is True
        rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines()))
        assert rows[0][0] == "品名" and rows[1][1] == "7"

    def test_missing_file_structured_error(self, tmp_path):
        res = structured_edit.editWorkbookCells(tmp_path / "nope.xlsx", {"A1": "x"})
        assert res["success"] is False and "不存在" in res["error"]

    def test_bad_cell_ref_structured_error(self, tmp_path):
        xlsx = _makeXlsx(tmp_path / "book.xlsx", [["a"]])
        res = structured_edit.editWorkbookCells(xlsx, {"1A": "x"})
        assert res["success"] is False and "非法单元格引用" in res["error"]

    def test_unsupported_extension(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("x", encoding="utf-8")
        res = structured_edit.editWorkbookCells(target, {"A1": "x"})
        assert res["success"] is False and "不支持的扩展名" in res["error"]

    def test_missing_sheet_named(self, tmp_path):
        xlsx = _makeXlsx(tmp_path / "book.xlsx", [["a"]])
        res = structured_edit.editWorkbookCells(
            xlsx, {"A1": "x"}, sheetName="不存在表")
        assert res["success"] is False and "工作表不存在" in res["error"]

    def test_openpyxl_missing_honest(self, tmp_path, monkeypatch):
        xlsx = _makeXlsx(tmp_path / "book.xlsx", [["a"]])

        def _boom():
            raise ImportError("No module named 'openpyxl'")

        monkeypatch.setattr(structured_edit, "_loadOpenpyxl", _boom)
        res = structured_edit.editWorkbookCells(xlsx, {"A1": "x"})
        assert res["success"] is False and "openpyxl" in res["error"]


class TestComputerDocEditTool:
    def _makeExecutor(self, workspace=None):
        agent = SimpleNamespace(
            config=SimpleNamespace(user_id="u1", agent_id="a1"),
            tool_memory=MagicMock(), tool_lifecycle=None, _skill_registry=None,
            tool_router=None, _current_user_input="x", _tool_messages_list=[],
            append_tool_messages=lambda records: None,
        )
        if workspace is not None:
            agent.workspace_path = str(workspace)
        return ToolExecutor(agent)

    def test_wiring_schema_dispatch_nonreproducible(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS

        assert "computer_doc_edit" in _BUILTIN_SCHEMAS
        assert _BUILTIN_SCHEMAS["computer_doc_edit"]["capability"]["readOnly"] is False
        assert "computer_doc_edit" in _NON_REPRODUCIBLE_TOOLS
        executor = self._makeExecutor()
        assert "computer_doc_edit" in executor._builtin_dispatch

    def test_handler_writes_inside_workspace_and_readback(self, tmp_path):
        _makeXlsx(tmp_path / "book.xlsx", [["a"]])
        executor = self._makeExecutor(tmp_path)
        res = asyncio.run(executor._execute_computer_doc_edit({
            "file_path": "book.xlsx",
            "cell_values": {"A1": "改了", "B1": "3"},
        }))
        assert res["success"] is True
        assert res["readback"]["A1"] == "改了" and res["readback"]["B1"] == 3

    def test_handler_rejects_path_outside_workspace(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        _makeXlsx(outside / "book.xlsx", [["a"]])
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        executor = self._makeExecutor(workspace)
        res = asyncio.run(executor._execute_computer_doc_edit({
            "file_path": str(outside / "book.xlsx"),
            "cell_values": {"A1": "x"},
        }))
        assert res.get("success") is not True, "工作区外路径必须被白名单拒绝"

    def test_handler_holds_desktop_lane(self, tmp_path):
        """desktop 车道被他线占用时，结构化直写必须被拒（与 GUI 动作互斥）。"""
        import threading

        from neurova.computer_use.lane_mutex import DESKTOP_LANE, get_lane_mutex

        _makeXlsx(tmp_path / "book.xlsx", [["a"]])
        executor = self._makeExecutor(tmp_path)
        started = threading.Event()
        release = threading.Event()

        def _occupy():
            with get_lane_mutex().hold(DESKTOP_LANE, owner="other-session"):
                started.set()
                release.wait(5)

        occupier = threading.Thread(target=_occupy)
        occupier.start()
        assert started.wait(5), "占道线程未就绪"
        try:
            res = asyncio.run(executor._execute_computer_doc_edit({
                "file_path": "book.xlsx", "cell_values": {"A1": "x"},
            }))
            assert res.get("success") is False
            assert res.get("guardrail", {}).get("code") == "lane_busy"
        finally:
            release.set()
            occupier.join(5)
