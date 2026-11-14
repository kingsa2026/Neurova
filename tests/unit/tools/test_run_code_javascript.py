# -*- coding: utf-8 -*-
"""P3-14 对照：run_code 的 JavaScript 执行（node -e 内联；node 缺席诚实报错）。
"""

from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


def _executor():
    return ToolExecutor(MagicMock())


class TestRunCodeJavaScript:
    @pytest.mark.asyncio
    async def test_javascript_executes_via_node(self):
        result = await _executor()._execute_run_code(
            {"code": "console.log('hello-js');", "language": "javascript"}
        )
        assert result["success"] is True
        assert "hello-js" in result["stdout"]

    @pytest.mark.asyncio
    async def test_js_alias_works(self):
        result = await _executor()._execute_run_code(
            {"code": "const sum = [1, 2, 3].reduce((a, b) => a + b, 0); console.log(sum);",
             "language": "js"}
        )
        assert result["success"] is True
        assert "6" in result["stdout"]

    @pytest.mark.asyncio
    async def test_javascript_error_surfaces(self):
        result = await _executor()._execute_run_code(
            {"code": "throw new Error('js 炸了');", "language": "javascript"}
        )
        assert result["success"] is False
        assert "js 炸了" in result["stderr"]

    @pytest.mark.asyncio
    async def test_node_missing_reports_honestly(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)
        result = await _executor()._execute_run_code(
            {"code": "console.log('x')", "language": "javascript"}
        )
        assert result["success"] is False
        assert "node 不可用" in result["error"]
