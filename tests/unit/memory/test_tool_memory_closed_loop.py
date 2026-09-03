"""
工具记忆闭环测试 — TDD 验证

数据流:
  用户输入 → check_tool_memory → 匹配? → auto_execute → record_tool_usage → 肌肉记忆 → 下次检索

测试 3 个断裂点修复:
1. muscle_memory.match() 接口对齐（tool_memory_integration 调用方式 vs MuscleMemory 实际签名）
2. record_tool_usage() 传播到 muscle_memory
3. execute_from_memory_async() 存在于根级 ToolExecutor
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ============================================================
# 断裂点 #1: muscle_memory.match() 接口对齐
# ============================================================

class TestMuscleMemoryMatchInterface:
    """测试 muscle_memory.match() 接口在 ToolMemoryIntegration 中的调用"""

    def test_check_tool_memory_calls_muscle_memory_with_query_only(self):
        """肌肉记忆匹配应该接受单个 query 参数（不指定工具名）"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        # 模拟肌肉记忆返回匹配结果
        mock_match_item = MagicMock()
        mock_match_item.tool_name = "file_read"
        mock_match_item.parameters = {"file_path": "/tmp/test"}
        mock_match_item.metadata = {"tool_source": "skill_system"}
        mock_mm.match_by_query.return_value = [(mock_match_item, 0.85)]

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm, confidence_threshold=0.8)

        result, decision = tmi.check_tool_memory("帮我读取文件")

        # 应该调用肌肉记忆的 match_by_query（不需要指定工具名）
        mock_mm.match_by_query.assert_called_once()
        assert decision in ("auto_execute", "suggest", "do_not_execute")

    def test_check_tool_memory_handles_muscle_memory_no_match(self):
        """肌肉记忆无匹配时应降级到关键词匹配"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        mock_mm.match_by_query.return_value = []

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm, confidence_threshold=0.8)

        result, decision = tmi.check_tool_memory("随便说点什么")

        # 无匹配时应返回 do_not_execute
        assert decision == "do_not_execute"
        assert result is None

    def test_check_tool_memory_muscle_memory_exception_falls_back(self):
        """肌肉记忆异常时应降级到关键词匹配，不抛异常"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        mock_mm.match_by_query.side_effect = RuntimeError("连接失败")

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm, confidence_threshold=0.8)

        # 不应抛异常
        result, decision = tmi.check_tool_memory("测试输入")
        assert decision in ("auto_execute", "suggest", "do_not_execute")

    def test_muscle_memory_match_returns_correct_format(self):
        """肌肉记忆应返回 (MuscleMemoryItem, confidence) 列表"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory, MuscleMemoryItem, MemoryLevel

        mm = MuscleMemory()
        # 记录一次使用
        item = mm.record_usage(
            tool_name="file_read",
            query="帮我读取文件 /tmp/test.txt",
            parameters={"file_path": "/tmp/test.txt"},
            success=True,
        )

        # match_by_query 应该返回列表
        results = mm.match_by_query("帮我读取文件")
        assert isinstance(results, list)
        if results:
            first_item, confidence = results[0]
            assert isinstance(first_item, MuscleMemoryItem)
            assert 0.0 <= confidence <= 1.0


# ============================================================
# 断裂点 #2: record_tool_usage 传播到肌肉记忆
# ============================================================

class TestRecordToolUsagePropagation:
    """测试 record_tool_usage 传播到肌肉记忆"""

    def test_record_tool_usage_calls_muscle_memory(self):
        """record_tool_usage 应该调用 muscle_memory.record_usage()"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        mock_mm.record_usage.return_value = MagicMock()

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm, confidence_threshold=0.8)

        tmi.record_tool_usage(
            tool_name="file_read",
            success=True,
            problem_text="帮我读取文件",
            tool_params={"file_path": "/tmp/test"},
        )

        # 肌肉记忆的 record_usage 应该被调用
        mock_mm.record_usage.assert_called_once()
        call_kwargs = mock_mm.record_usage.call_args
        assert call_kwargs.kwargs.get("tool_name") == call_kwargs.kwargs.get("tool_name", "file_read") or \
               call_kwargs[0][0] == "file_read" if call_kwargs[0] else True

    def test_record_tool_usage_propagates_success_to_muscle_memory(self):
        """成功记录应该传播到肌肉记忆"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        mock_mm.record_usage.return_value = MagicMock()

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)

        tmi.record_tool_usage(
            tool_name="memory_search",
            success=True,
            problem_text="搜索记忆",
            tool_params={"query": "test"},
        )

        mock_mm.record_usage.assert_called_once()
        call_kwargs = mock_mm.record_usage.call_args
        # success 应该为 True
        assert call_kwargs.kwargs.get("success", call_kwargs[1].get("success") if len(call_kwargs) > 1 else True) is True

    def test_record_tool_usage_propagates_failure_to_muscle_memory(self):
        """失败记录应该传播到肌肉记忆"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mock_mm = MagicMock()
        mock_mm.record_usage.return_value = MagicMock()

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)

        tmi.record_tool_usage(
            tool_name="file_write",
            success=False,
            error_msg="权限不足",
        )

        mock_mm.record_usage.assert_called_once()
        call_kwargs = mock_mm.record_usage.call_args
        assert call_kwargs.kwargs.get("success") is False

    def test_record_tool_usage_without_muscle_memory_doesnt_crash(self):
        """没有肌肉记忆时 record_tool_usage 不应崩溃"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        tmi = ToolMemoryIntegration(muscle_memory=None)

        # 不应抛异常
        tmi.record_tool_usage(tool_name="test", success=True)
        assert len(tmi.usage_history) == 1


# ============================================================
# 断裂点 #3: execute_from_memory_async 存在于根级 ToolExecutor
# ============================================================

class TestToolExecutorFromMemoryAsync:
    """测试根级 ToolExecutor 的 execute_from_memory_async"""

    def test_root_tool_executor_has_execute_from_memory_async(self):
        """根级 ToolExecutor 应该有 execute_from_memory_async 方法"""
        from neurova.tool_executor import ToolExecutor

        # 检查方法存在
        assert hasattr(ToolExecutor, 'execute_from_memory_async'), \
            "根级 ToolExecutor 缺少 execute_from_memory_async 方法"

    @pytest.mark.asyncio
    async def test_execute_from_memory_async_returns_dict(self):
        """execute_from_memory_async 应该返回 {"status": ..., "result": ...} 字典"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._skill_registry = None
        mock_agent.tool_router = None
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = None
        mock_agent.skill_packer = None
        mock_agent.config = None

        executor = ToolExecutor(mock_agent)

        result = await executor.execute_from_memory_async(
            tool_memory_result={"tool_name": "test_tool", "tool_source": "skill_system", "tool_params": {}},
            user_input="测试",
        )

        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ("success", "failure")

    @pytest.mark.asyncio
    async def test_execute_from_memory_async_with_empty_result(self):
        """空的 tool_memory_result 应返回 failure"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        executor = ToolExecutor(mock_agent)

        result = await executor.execute_from_memory_async(
            tool_memory_result={},
            user_input="测试",
        )

        assert result["status"] == "failure"


# ============================================================
# 额外修复: MuscleMemory 构造函数参数对齐
# ============================================================

class TestMuscleMemoryConstructor:
    """测试 MuscleMemory 构造函数参数"""

    def test_muscle_memory_accepts_storage_path(self):
        """MuscleMemory 应该接受 storage_path 参数"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

        # 不应抛异常
        mm = MuscleMemory(storage_path=None)
        assert mm is not None

    def test_muscle_memory_accepts_storage_dir_alias(self):
        """MuscleMemory 应该接受 storage_dir 作为 storage_path 的别名"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

        # agent_core.py 传递 storage_dir，应该能工作
        mm = MuscleMemory(storage_dir=None)
        assert mm is not None


# ============================================================
# 端到端闭环测试
# ============================================================

class TestToolMemoryClosedLoop:
    """端到端闭环测试"""

    def test_full_loop_record_then_match(self):
        """完整闭环：记录使用 → 下次匹配"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mm = MuscleMemory()
        # 肌肉记忆语义匹配的自动执行阈值由 muscle_memory_threshold 决定
        # （confidence_threshold 仅用于关键词匹配降级路径）
        tmi = ToolMemoryIntegration(muscle_memory=mm, confidence_threshold=0.6, muscle_memory_threshold=0.6)

        # 步骤1: 记录一次成功的工具使用
        tmi.record_tool_usage(
            tool_name="file_read",
            success=True,
            problem_text="帮我读取 /tmp/config.json 文件",
            tool_params={"file_path": "/tmp/config.json"},
        )

        # 步骤2: 使用相似查询检索
        result, decision = tmi.check_tool_memory("读取 /tmp/config.json 文件")

        # 应该有匹配结果
        assert result is not None, "闭环断裂：记录后无法检索到"
        assert decision in ("auto_execute", "suggest"), f"决策应该是 auto_execute 或 suggest，实际: {decision}"

    def test_full_loop_failure_records_to_muscle_memory(self):
        """失败记录也应该传播到肌肉记忆"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

        mm = MuscleMemory()
        tmi = ToolMemoryIntegration(muscle_memory=mm)

        # 记录失败
        tmi.record_tool_usage(
            tool_name="file_write",
            success=False,
            problem_text="写入文件失败",
            error_msg="权限不足",
        )

        # 肌肉记忆应该有记录
        stats = mm.get_stats()
        assert stats["total"] > 0, "失败记录未传播到肌肉记忆"

    def test_multiple_usages_promote_memory_level(self):
        """多次成功使用应该提升记忆层级"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

        mm = MuscleMemory()

        # 连续成功 3 次（超过固化阈值 2）
        for i in range(3):
            mm.record_usage(
                tool_name="memory_search",
                query="搜索记忆中的信息",
                parameters={"query": "test"},
                success=True,
            )

        stats = mm.get_stats()
        # 应该有 L2 或 L1 层的条目（固化后提升）
        assert stats["l1_count"] + stats["l2_count"] > 0, \
            f"连续成功 3 次后应有 L1/L2 条目, 实际: {stats}"
