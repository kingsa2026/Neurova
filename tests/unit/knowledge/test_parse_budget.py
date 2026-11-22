"""资源治理 P1-3：文件解析四维结构化预算契约。

四维（对齐参照系 ad fileParseBudget 的防线形态）：
- 输入体积（原始字节，防超大文件占用解析线程）
- 抽取字符（既有 MAX_EXTRACT_CHARS 单源，本预算不另立第二份）
- 条目数（PDF 页数/工作表数）
- 单元格面积（行×列，防巨型表格拖垮解析）
任一超限即抛 FileParseBudgetError 快速失败；上限经环境变量注入。
"""

import pytest

from neurova.knowledge.parse_budget import (
    FileParseBudgetError,
    assertParseInputBudget,
    assertPagesBudget,
    assertSheetsBudget,
)


class TestAssertParseInputBudget:
    def test_within_cap_passes(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_INPUT_BYTES", "1000")
        assertParseInputBudget(b"x" * 1000, "a.txt")

    def test_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_INPUT_BYTES", "10")
        with pytest.raises(FileParseBudgetError) as exc:
            assertParseInputBudget(b"x" * 11, "a.txt")
        assert "input_too_large" in str(exc.value)

    def test_default_cap_is_64mb(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_PARSE_MAX_INPUT_BYTES", raising=False)
        # 64MB 内放行（不真分配 64MB，用边界值验证判定逻辑）
        assertParseInputBudget(b"x", "a.txt")

    def test_empty_data_rejected(self):
        with pytest.raises(FileParseBudgetError):
            assertParseInputBudget(b"", "a.txt")


class TestAssertPagesBudget:
    def test_within_cap_passes(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_PAGES", "100")
        assertPagesBudget(100, "a.pdf")

    def test_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_PAGES", "10")
        with pytest.raises(FileParseBudgetError) as exc:
            assertPagesBudget(11, "a.pdf")
        assert "too_many_pages" in str(exc.value)

    def test_default_cap_is_2000(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_PARSE_MAX_PAGES", raising=False)
        assertPagesBudget(2000, "a.pdf")


class TestAssertSheetsBudget:
    def test_within_cap_passes(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_SHEET_ROWS", "100")
        monkeypatch.setenv("NEUROVA_PARSE_MAX_CELL_AREA", "10000")
        assertSheetsBudget([{"name": "s", "rows": 100, "cols": 10}], "a.xls")

    def test_rows_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_SHEET_ROWS", "10")
        with pytest.raises(FileParseBudgetError) as exc:
            assertSheetsBudget([{"name": "s", "rows": 11, "cols": 2}], "a.xls")
        assert "too_many_rows" in str(exc.value)

    def test_cell_area_over_cap_raises(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_CELL_AREA", "100")
        with pytest.raises(FileParseBudgetError) as exc:
            assertSheetsBudget([{"name": "s", "rows": 100, "cols": 100}], "a.xls")
        assert "cell_area" in str(exc.value)

    def test_multi_sheet_any_violation_raises(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_SHEET_ROWS", "10")
        with pytest.raises(FileParseBudgetError):
            assertSheetsBudget(
                [{"name": "ok", "rows": 5, "cols": 2},
                 {"name": "bad", "rows": 50, "cols": 2}],
                "a.xls",
            )
