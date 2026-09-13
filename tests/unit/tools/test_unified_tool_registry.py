"""
UnifiedToolRegistry 单元测试

2026-09-13 残留处理：原文件按一套从未存在的契约书写（构造参数 tool_router/
tool_engine、register_builtin 的 category/parameters→ToolDefinition 转换、
execute_and_log 的 agent_id/user_id 与 dict 返回、Router 委托、latency_ms
键——全 git 历史 -S 检索零命中；实现自入库即下述简化契约，A-8 已登记该类为
零生产消费死代码待裁决）。本文件更新到**实现真实契约**
（neurova/tool_layers/unified_registry.py），验证意图逐条保留：初始化、
注册（单条/批量/引擎同步/手动入引擎/引擎缺席容错/同步失败不阻断）、
延迟子模块、execute_and_log 成功/异常/未注册/日志落位。
"""

import unittest
import asyncio
from unittest.mock import Mock, AsyncMock

from neurova.tool_layers.unified_registry import UnifiedToolRegistry


class TestUnifiedToolRegistryInit(unittest.TestCase):
    """初始化（真实签名：无参构造）"""

    def test_init_default(self):
        registry = UnifiedToolRegistry()
        self.assertIsNone(registry._execution_engine)
        self.assertEqual(registry._builtin_tools, {})
        self.assertTrue(registry._sync_to_engine)


class TestRegisterBuiltin(unittest.TestCase):
    """内置工具注册与引擎同步"""

    def test_register_builtin_stores_and_tags(self):
        registry = UnifiedToolRegistry()
        tool = Mock()
        registry.register_builtin("double", tool)
        self.assertIs(registry._builtin_tools["double"], tool)
        self.assertEqual(registry._tool_metadata["double"]["source"], "builtin")

    def test_register_builtin_syncs_to_engine_when_set(self):
        registry = UnifiedToolRegistry()
        engine = Mock()
        registry.set_execution_engine(engine)
        tool = Mock()
        registry.register_builtin("double", tool)
        # 真实契约：引擎收到 name+tool 原样（无 ToolDefinition 转换）
        engine.register_tool.assert_called_once_with("double", tool)

    def test_register_builtin_without_engine_is_noop_safe(self):
        registry = UnifiedToolRegistry()
        registry.register_builtin("solo", Mock())  # 无引擎不抛
        self.assertIn("solo", registry._builtin_tools)

    def test_register_builtin_batch(self):
        registry = UnifiedToolRegistry()
        engine = Mock()
        registry.set_execution_engine(engine)
        registry.register_builtin_batch({"a": Mock(), "b": Mock()})
        self.assertEqual(set(registry._builtin_tools.keys()), {"a", "b"})
        self.assertEqual(engine.register_tool.call_count, 2)

    def test_engine_sync_failure_does_not_break(self):
        registry = UnifiedToolRegistry()
        engine = Mock()
        engine.register_tool.side_effect = RuntimeError("engine down")
        registry.set_execution_engine(engine)
        registry.register_builtin("t", Mock())  # 同步失败仅 warning，注册仍在
        self.assertIn("t", registry._builtin_tools)

    def test_register_to_engine_manual(self):
        registry = UnifiedToolRegistry()
        engine = Mock()
        registry.set_execution_engine(engine)
        tool = Mock()
        registry.register_to_engine("x", tool)
        engine.register_tool.assert_called_once_with("x", tool)


class TestLazySubmodules(unittest.TestCase):
    """延迟加载子模块（真实公共面）"""

    def test_get_capability_graph(self):
        registry = UnifiedToolRegistry()
        graph = registry.get_capability_graph()
        self.assertIsNotNone(graph)
        # 实现的关系查询面（残留处理：原断言 get_related_tools 从未存在）
        self.assertTrue(hasattr(graph, "suggest_companion_tools"))
        self.assertTrue(hasattr(graph, "get_prerequisites"))

    def test_get_cli_executor(self):
        registry = UnifiedToolRegistry()
        self.assertIsNotNone(registry.get_cli_executor())

    def test_get_tool_logger(self):
        registry = UnifiedToolRegistry()
        self.assertIsNotNone(registry.get_tool_logger())


class TestExecuteAndLog(unittest.TestCase):
    """execute_and_log（真实契约：两参、返回 ToolExecutionResult 对象）"""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_execute_success(self):
        registry = UnifiedToolRegistry()
        tool = AsyncMock()
        tool.execute.return_value = {"result": "ok"}
        registry.register_builtin("test_tool", tool)
        result = self._run(registry.execute_and_log("test_tool", {"p": 1}))
        self.assertTrue(result.success)
        self.assertEqual(result.tool_name, "test_tool")
        self.assertEqual(result.output, {"result": "ok"})
        self.assertIsNone(result.error)

    def test_execute_non_dict_result_wrapped(self):
        registry = UnifiedToolRegistry()
        tool = AsyncMock()
        tool.execute.return_value = "plain-text"
        registry.register_builtin("t", tool)
        result = self._run(registry.execute_and_log("t", {}))
        self.assertEqual(result.output, {"result": "plain-text"})

    def test_execute_exception_returns_error_result(self):
        registry = UnifiedToolRegistry()
        tool = AsyncMock()
        tool.execute.side_effect = ValueError("boom")
        registry.register_builtin("bad_tool", tool)
        result = self._run(registry.execute_and_log("bad_tool", {}))
        self.assertFalse(result.success)
        self.assertIn("boom", result.error or "")

    def test_execute_unknown_tool_error_message(self):
        registry = UnifiedToolRegistry()
        result = self._run(registry.execute_and_log("ghost", {}))
        self.assertFalse(result.success)
        self.assertIn("Tool not found: ghost", result.error or "")

    def test_execution_logged_as_entry_object(self):
        registry = UnifiedToolRegistry()
        tool = AsyncMock()
        tool.execute.return_value = {"result": 1}
        registry.register_builtin("t", tool)
        fake_logger = Mock()
        registry._tool_logger = fake_logger
        self._run(registry.execute_and_log("t", {"a": 1}))
        fake_logger.log.assert_called_once()
        entry = fake_logger.log.call_args.args[0]
        self.assertEqual(entry.tool_name, "t")


if __name__ == "__main__":
    unittest.main()
