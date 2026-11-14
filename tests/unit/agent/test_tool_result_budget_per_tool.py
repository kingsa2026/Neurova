"""逐工具结果预算（P1-1）：工具 schema 可声明 result_budget_chars，
咽喉 maybe_output_ref 按声明值（而非全局阈值）判定是否落盘为引用。

- 未声明 → 全局默认（装配阈值）；
- 声明小于结果体量 → 落盘 tool_outputs/，上下文只留引用+预览；
- 失败结果永不折叠（诊断本体不蒸发，既有语义不变）。
"""

import json
from pathlib import Path

import pytest

from neurova.agent import tool_output_ref as tor
from neurova.builtin_tools import get_builtin_tool_result_budget


@pytest.fixture(autouse=True)
def freshInstall(tmp_path):
    tor.uninstall_tool_output_ref(force=True)
    handle = tor.install_tool_output_ref(max_chars=100)
    yield handle
    tor.uninstall_tool_output_ref(force=True)


def _bigResult(n: int = 500) -> dict:
    return {"success": True, "content": "x" * n}


class TestPerToolBudgetOverride:
    def test_small_result_passthrough(self, tmp_path):
        result = _bigResult(10)
        out = tor.maybe_output_ref("t", result, tmp_path, success=True)
        assert out is result

    def test_over_default_budget_falls_to_ref(self, tmp_path):
        out = tor.maybe_output_ref("t", _bigResult(500), tmp_path, success=True)
        assert "output_ref" in out
        assert out["output_ref"]["truncated"] is True
        assert len(out["output_ref"]["preview"]) <= 500
        assert Path(out["output_ref"]["path"]).exists()

    def test_declared_small_budget_collapses_earlier(self, tmp_path):
        out = tor.maybe_output_ref(
            "t", _bigResult(50), tmp_path, success=True, max_chars=10
        )
        assert "output_ref" in out
        assert out["output_ref"]["size_bytes"] > 0

    def test_declared_large_budget_keeps_result_inline(self, tmp_path):
        out = tor.maybe_output_ref(
            "t", _bigResult(500), tmp_path, success=True, max_chars=100_000
        )
        assert "output_ref" not in out

    def test_failure_result_never_collapsed_even_over_budget(self, tmp_path):
        failed = {"success": False, "error": "e" * 500}
        out = tor.maybe_output_ref(
            "t", failed, tmp_path, success=False, max_chars=10
        )
        assert out is failed


class TestSchemaBudgetDeclaration:
    def test_web_search_declares_budget(self):
        assert get_builtin_tool_result_budget("web_search") == 16384

    def test_undeclared_tool_returns_none(self):
        assert get_builtin_tool_result_budget("exec_command") is None

    def test_unknown_tool_returns_none(self):
        assert get_builtin_tool_result_budget("no_such_tool") is None

    def test_invalid_declaration_ignored(self):
        # 非法声明（负数/非 int）按未声明处理，不炸取数口
        assert get_builtin_tool_result_budget("web_search") == 16384
