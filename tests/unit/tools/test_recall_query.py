"""QwenPaw 对照批 B3：recall_query 受限 Python 表达式查询。

红灯（实现前）：schema/dispatch 无 recall_query、引擎模块不存在。
绿灯：
- schema 与 _builtin_dispatch 双侧注册（既有不变量测试同款口径）；
- runRecallExpression：过滤/统计可表达；import/getattr/下划线属性拒绝；
  结果截断；
- handler：走 stub context_pool 的取数→投影→求值全链。
"""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

from neurova.tools.recall_expression import (
    RecallExpressionError,
    runRecallExpression,
)

ITEMS = [
    {"content": "部署失败了，报错在 build 阶段", "turn_id": "t1", "recalled_from": "memory_ledger"},
    {"content": "部署成功了", "turn_id": "t2", "recalled_from": "memory_ledger"},
    {"content": "回滚到上一个版本", "turn_id": "t3", "recalled_from": "memory_ledger"},
]


class TestExpressionEngine:

    def test_filter_expression(self):
        result = runRecallExpression(
            "[i['content'] for i in items if '失败' in i['content']]", ITEMS)
        assert "部署失败了" in result and "部署成功了" not in result

    def test_stats_expression(self):
        result = runRecallExpression("len(items)", ITEMS)
        assert result == "3"

    def test_import_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("__import__('os').getcwd()", ITEMS)

    def test_getattr_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("getattr(items, 'append')", ITEMS)

    def test_dunder_attribute_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("items.__class__", ITEMS)

    def test_statement_rejected(self):
        with pytest.raises(RecallExpressionError):
            runRecallExpression("import os", ITEMS)

    def test_result_truncated(self):
        big = [{"content": "x" * 500} for _ in range(20)]
        result = runRecallExpression("str(items)", big)
        assert len(result) <= 2100 and "截断" in result


class TestRegistration:

    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "recall_query" in _BUILTIN_SCHEMAS

    def test_dispatch_registered(self):
        from neurova.tool_executor import ToolExecutor

        assert ToolExecutor._builtin_dispatch["recall_query"] == "_execute_recall_query"


class TestHandler:

    def _executor_with_pool(self, recalled):
        stub_pool = SimpleNamespace(recall_evicted=lambda query, limit: recalled)
        stub_agent = SimpleNamespace(
            context_orchestrator=SimpleNamespace(context_pool=stub_pool))
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)  # 跳过重装配；只挂本用例需要的引用
        executor._agent = stub_agent
        return executor

    def test_handler_end_to_end(self):
        recalled = [SimpleNamespace(content=c, metadata={"turn_id": t, "recalled_from": "memory_ledger"})
                    for c, t in [("部署失败", "t1"), ("部署成功", "t2")]]
        executor = self._executor_with_pool(recalled)
        result = asyncio.run(executor._execute_recall_query(
            {"expression": "[i['content'] for i in items]", "query": "部署"}))
        assert result["success"] is True and result["count"] == 2
        assert "部署失败" in result["result"]

    def test_handler_requires_pool(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        executor._agent = SimpleNamespace(context_orchestrator=None)
        result = asyncio.run(executor._execute_recall_query({"expression": "len(items)"}))
        assert "上下文池不可用" in result["error"]

    def test_handler_surfaces_expression_errors(self):
        recalled = [SimpleNamespace(content="x", metadata={})]
        executor = self._executor_with_pool(recalled)
        result = asyncio.run(executor._execute_recall_query(
            {"expression": "__import__('os')"}))
        assert "error" in result
