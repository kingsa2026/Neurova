"""
ToolExecutor.on_tool_executed 签名匹配与闭环学习测试

复现 P0 BUG:
  1. 方法名不匹配: 调用 on_tool_executed, 定义 _on_tool_executed
  2. 参数签名不匹配: 调用传 6 参, 定义只接受 3 参
  3. 内部调用不存在的 update_usage (应为 touch)
  4. 参数语义错误: result 被当作 tool_params 传入

修复目标:
  - on_tool_executed 为公开方法, 6 参数签名
  - 正确转发到 tool_memory.record_tool_usage (全参数)
  - 正确转发到 tool_lifecycle.touch (不是 update_usage)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from neurova.tool_executor import ToolExecutor


class TestOnToolExecutedSignature:
    """验证 on_tool_executed 公开接口签名"""

    def test_public_method_exists(self):
        """on_tool_executed 必须作为公开方法存在 (无下划线前缀)"""
        executor = ToolExecutor(agent_ref=Mock())
        # BUG 1: 当前只有 _on_tool_executed, 会 AttributeError
        assert hasattr(executor, "on_tool_executed"), (
            "on_tool_executed 必须是公开方法 (agent_core.py:1103 调用的是 on_tool_executed)"
        )

    def test_accepts_six_parameters(self):
        """on_tool_executed 必须接受 6 个参数 (与 agent_core.py:1103 调用一致)"""
        executor = ToolExecutor(agent_ref=Mock())
        # BUG 2: 当前签名只接受 3 参, 会 TypeError
        # 调用方签名: tool_name, params, user_input, success, tool_source, execution_time
        executor.on_tool_executed(
            tool_name="search",
            params={"query": "test"},
            user_input="搜索测试",
            success=True,
            tool_source="skill_system",
            execution_time=1.5,
        )


class TestOnToolExecutedForwardsToToolMemory:
    """验证 on_tool_executed 正确转发到 tool_memory.record_tool_usage"""

    def test_forwards_all_parameters_to_tool_memory(self):
        """record_tool_usage 必须收到全部 6 个参数 (非仅 3 个)"""
        mock_tool_memory = MagicMock()
        mock_agent = Mock()
        mock_agent.tool_memory = mock_tool_memory
        mock_agent.tool_lifecycle = None  # 隔离 lifecycle

        executor = ToolExecutor(agent_ref=mock_agent)

        executor.on_tool_executed(
            tool_name="search",
            params={"query": "hello"},
            user_input="搜索 hello",
            success=True,
            tool_source="skill_system",
            execution_time=2.0,
        )

        # BUG 4: 当前把 result 当作 tool_params, 且丢失 user_input/tool_source/execution_time
        mock_tool_memory.record_tool_usage.assert_called_once()
        call_kwargs = mock_tool_memory.record_tool_usage.call_args.kwargs

        assert call_kwargs.get("tool_name") == "search"
        assert call_kwargs.get("success") is True
        assert call_kwargs.get("execution_time") == 2.0
        assert call_kwargs.get("problem_text") == "搜索 hello"
        assert call_kwargs.get("tool_source") == "skill_system"
        assert call_kwargs.get("tool_params") == {"query": "hello"}

    def test_does_not_pass_result_as_tool_params(self):
        """params 是工具参数, 不是执行结果 (语义纠正)"""
        mock_tool_memory = MagicMock()
        mock_agent = Mock()
        mock_agent.tool_memory = mock_tool_memory
        mock_agent.tool_lifecycle = None

        executor = ToolExecutor(agent_ref=mock_agent)

        # params 是工具参数字典
        executor.on_tool_executed(
            tool_name="weather",
            params={"city": "北京"},
            user_input="北京天气",
            success=True,
            tool_source="builtin",
            execution_time=0.5,
        )

        call_kwargs = mock_tool_memory.record_tool_usage.call_args.kwargs
        # tool_params 必须是 {"city": "北京"}, 不能是执行结果
        assert call_kwargs.get("tool_params") == {"city": "北京"}


class TestOnToolExecutedForwardsToToolLifecycle:
    """验证 on_tool_executed 正确转发到 tool_lifecycle.touch (不是 update_usage)"""

    def test_calls_touch_not_update_usage(self):
        """必须调用 touch 方法 (ToolLifecycleManager 真实方法), 不是 update_usage"""
        mock_lifecycle = MagicMock()
        # BUG 3: 当前代码调用 update_usage, 该方法不存在
        # 真实方法是 touch(tool_name, success)
        mock_agent = Mock()
        mock_agent.tool_memory = None  # 隔离 tool_memory
        mock_agent.tool_lifecycle = mock_lifecycle

        executor = ToolExecutor(agent_ref=mock_agent)

        executor.on_tool_executed(
            tool_name="search",
            params={"query": "test"},
            user_input="test",
            success=True,
            tool_source="builtin",
            execution_time=1.0,
        )

        # 必须调用 touch, 不是 update_usage
        mock_lifecycle.touch.assert_called_once_with("search", True)
        mock_lifecycle.update_usage.assert_not_called()

    def test_forwards_failure_to_touch(self):
        """失败时 success=False 必须正确转发到 touch"""
        mock_lifecycle = MagicMock()
        mock_agent = Mock()
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = mock_lifecycle

        executor = ToolExecutor(agent_ref=mock_agent)

        executor.on_tool_executed(
            tool_name="weather",
            params={"city": "火星"},
            user_input="火星天气",
            success=False,
            tool_source="builtin",
            execution_time=0.1,
        )

        mock_lifecycle.touch.assert_called_once_with("weather", False)


class TestOnToolExecutedRobustness:
    """验证 on_tool_executed 容错性"""

    def test_no_tool_memory_no_crash(self):
        """tool_memory 为 None 时不应崩溃"""
        mock_agent = Mock()
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = None

        executor = ToolExecutor(agent_ref=mock_agent)

        # 不应抛出异常
        executor.on_tool_executed(
            tool_name="search",
            params={},
            user_input="test",
            success=True,
            tool_source="test",
            execution_time=0.0,
        )

    def test_tool_memory_exception_does_not_propagate(self):
        """tool_memory 内部异常不应传播到调用方"""
        mock_tool_memory = MagicMock()
        mock_tool_memory.record_tool_usage.side_effect = RuntimeError("DB error")
        mock_agent = Mock()
        mock_agent.tool_memory = mock_tool_memory
        mock_agent.tool_lifecycle = None

        executor = ToolExecutor(agent_ref=mock_agent)

        # 不应抛出异常 (闭环学习的失败不应阻断主流程)
        executor.on_tool_executed(
            tool_name="search",
            params={},
            user_input="test",
            success=True,
            tool_source="test",
            execution_time=0.0,
        )
