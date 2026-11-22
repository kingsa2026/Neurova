"""资源治理 P1-3：parse_document 的解析预算接线。

- 输入体积超限 → FileParseBudgetError（在进入任何格式分支/旧管线前快速失败）
- PDF 页数超限 → FileParseBudgetError
- XLS 工作表行数/面积超限 → FileParseBudgetError
上限经环境变量注入（调用时读取），小样本即可实证。
"""

import pytest

from neurova.knowledge.document_pipeline import parse_document
from neurova.knowledge.parse_budget import FileParseBudgetError


class TestInputBudgetWiring:
    def test_oversize_input_fails_fast(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_INPUT_BYTES", "10")
        with pytest.raises(FileParseBudgetError):
            parse_document(b"x" * 11, "a.txt")

    def test_within_budget_passes_through(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_INPUT_BYTES", "100000")
        # 小文本走完整管线；断言只针对预算契约——解析层自身失败
        # （如环境缺 kreuzberg）与本预算无关，不判失败。
        try:
            parse_document("# 标题\n\n正文\n", "a.md")
        except FileParseBudgetError:
            pytest.fail("预算内文件不得触发预算异常")
        except Exception:  # noqa: BLE001 - 非预算类解析失败不属本测试判定域
            pass


class TestPagesBudgetWiring:
    def test_pdf_pages_over_cap_fails_fast(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_PAGES", "3")
        # 关闭 kreuzberg 主路，确保走 pdf 逐页分支（预算判定点所在）
        monkeypatch.setattr(
            "neurova.knowledge.parser_shadow.kreuzbergMainEnabled", lambda ext: False
        )
        monkeypatch.setattr(
            "neurova.knowledge.document_pipeline.extract_pdf_pages",
            lambda data: ["p1", "p2", "p3", "p4"],
        )
        with pytest.raises(FileParseBudgetError):
            parse_document(b"%PDF-1.4 fake", "a.pdf")


class TestSheetsBudgetWiring:
    def test_xls_rows_over_cap_fails_fast(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PARSE_MAX_SHEET_ROWS", "2")
        monkeypatch.setattr(
            "neurova.knowledge.document_pipeline.extract_xls_sheets",
            lambda data: [{"name": "s", "rows": 5, "cols": 2}],
        )
        with pytest.raises(FileParseBudgetError):
            parse_document(b"fake-xls", "a.xls")
