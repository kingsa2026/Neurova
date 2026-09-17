"""
PostChatPipeline Step 9.96 接线测试

复现 P1.1 BUG:
  _step_extract_conversation_rules 已完整实现但未在 process() 中调用,
  导致对话规则提取、经验记忆融合、模式挖掘器更新全部失效。

修复目标:
  process() 在 Step 9.95 (version_snapshot) 之后、Step 10 (proactive_question) 之前
  调用 Step 9.96 (extract_conversation_rules)。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.post_chat_pipeline import PostChatPipeline, StepStatus


class TestStep996Wiring:
    """验证 Step 9.96 被正确接入 process() 流程"""

    def test_step_996_method_exists(self):
        """_step_extract_conversation_rules 方法必须存在"""
        assert hasattr(PostChatPipeline, "_step_extract_conversation_rules"), (
            "_step_extract_conversation_rules 方法必须存在 (post_chat_pipeline.py:1746)"
        )

    def test_step_996_called_in_process(self):
        """process() 必须调用 Step 9.96, 不能跳过"""
        # 创建一个最小化的 pipeline 实例用于检查 process() 源码
        import inspect

        source = inspect.getsource(PostChatPipeline.process)
        # BUG: 当前 process() 中没有调用 _step_extract_conversation_rules
        assert "_step_extract_conversation_rules" in source, (
            "process() 必须调用 _step_extract_conversation_rules (Step 9.96), "
            "当前为死代码, 对话规则提取完全失效"
        )

    def test_step_996_called_after_995(self):
        """Step 9.96 必须在 9.95 之后调用（依赖：快照先落，规则提取再消费）

        P0-1 变更：9.95/9.96 属响应无关旁路，已移入后台串链
        （_snapshot_then_rules），与响应路径的 Step 10（主动提问，结果随响应
        返回）不再有先后约束——原"9.96 必须在 Step 10 之前"的前提随之消失。
        此处只钉住真实存在的那条依赖：9.95 → 9.96。
        """
        import inspect

        source = inspect.getsource(PostChatPipeline.process)
        idx_995 = source.find("_step_version_snapshot")
        idx_996 = source.find("_step_extract_conversation_rules")

        assert idx_995 != -1, "Step 9.95 (_step_version_snapshot) 未找到"
        assert idx_996 != -1, "Step 9.96 (_step_extract_conversation_rules) 未找到"
        assert idx_995 < idx_996, "Step 9.96 必须在 9.95 之后（同一条后台串链）"

    @pytest.mark.asyncio
    async def test_step_996_executed_in_full_run(self):
        """完整 process() 运行时, Step 9.96 必须被执行 (非跳过)

        P0-1 变更：9.96 随 9.95 移入后台串链。断言改为等旁路步骤收尾
        （drain_background）后检查 _safe_step 实参——不再依赖"全部步骤同步
        跑完"的旧时序。
        """
        # 构造最小化 pipeline
        mock_agent = MagicMock()
        pipeline = PostChatPipeline(mock_agent)

        # Mock 所有依赖步骤, 让 process() 能跑完
        pipeline._safe_step = AsyncMock(
            side_effect=lambda name, coro, **kw: None
        )
        pipeline._safe_step_sync = MagicMock(
            side_effect=lambda name, fn, **kw: None
        )

        # Mock _get_dependency 返回 None (无依赖组件)
        pipeline._get_dependency = MagicMock(return_value=None)

        # Mock agent 属性
        mock_agent._collect_tool_messages = MagicMock(return_value=[])

        # 执行 process
        await pipeline.process(
            user_input="测试输入",
            reply="测试回复",
            session_id="test_session",
            save_memory=False,
            enable_tts=False,
            metadata={},
        )
        await pipeline.drain_background(timeout=5)

        # 验证 _safe_step 被调用时包含 extract_conversation_rules
        call_names = [
            call.args[0] if call.args else call.kwargs.get("name", "")
            for call in pipeline._safe_step.call_args_list
        ]
        assert "extract_conversation_rules" in call_names, (
            f"process() 必须调用 _safe_step('extract_conversation_rules', ...), "
            f"实际调用: {call_names}"
        )
