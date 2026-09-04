"""on_experience_recorded 结晶接线契约测试（经验结晶闭环审计 2026-09-04 修复 ⑦）

断点⑦：EvolutionOrchestrator 是全局单例，agent 初始化时把自己的 crystallizer
注入单例（agent_core.py:1251），多 agent 后初始化者获胜——A agent 的经验会结晶进
B agent 的 memory.db（跨 agent 污染）。
修复：on_experience_recorded 增加可选 crystallizer 参数，调用方（post_chat Step9）
显式传入 agent 自己的结晶器；未传时回退单例构造参数（向后兼容）。

同断点：纯对话轮（tools=[]）永不进入结晶缓冲（`if self.crystallizer and tools`）。
修复：空工具轮以 "chat" 伪工具名观察，与 EKB 的 skill_name="chat" 约定一致。
"""

from unittest.mock import MagicMock

import pytest

from neurova.evolution.closed_loop import EvolutionOrchestrator


class TestCrystallizerWiring:
    def test_pure_chat_round_observed_as_chat(self):
        """纯对话轮（无工具）也要进结晶缓冲（入口放宽）"""
        orch = EvolutionOrchestrator()
        cryst = MagicMock()
        orch.on_experience_recorded(
            text="t", task="问天气", tools=[], success=True, crystallizer=cryst
        )
        cryst.observe.assert_called_once_with(
            tool_name="chat", context="问天气", success=True
        )

    def test_tool_round_observes_each_tool(self):
        orch = EvolutionOrchestrator()
        cryst = MagicMock()
        orch.on_experience_recorded(
            text="t", task="task", tools=["w1", "w2"], success=True, crystallizer=cryst
        )
        assert cryst.observe.call_count == 2
        cryst.observe.assert_any_call(tool_name="w1", context="task", success=True)
        cryst.observe.assert_any_call(tool_name="w2", context="task", success=True)

    def test_caller_crystallizer_overrides_singleton_injection(self):
        """agent 级隔离：显式传入的 crystallizer 必须覆盖单例上被注入的旧实例"""
        orch = EvolutionOrchestrator()
        own = MagicMock()
        caller = MagicMock()
        orch.crystallizer = own  # 模拟 last-writer-wins 注入的旧态
        orch.on_experience_recorded(
            text="t", task="task", tools=["w1"], success=True, crystallizer=caller
        )
        caller.observe.assert_called_once_with(
            tool_name="w1", context="task", success=True
        )
        own.observe.assert_not_called()

    def test_legacy_constructor_crystallizer_still_observed(self):
        """向后兼容：构造参数注入的 crystallizer 在调用方未显式传入时仍生效"""
        cryst = MagicMock()
        orch = EvolutionOrchestrator(crystallizer=cryst)
        orch.on_experience_recorded(text="t", task="task", tools=["w1"], success=True)
        cryst.observe.assert_called_once()

    def test_no_crystallizer_is_noop(self):
        """无结晶器时经验记录不炸"""
        orch = EvolutionOrchestrator()  # crystallizer=None
        result = orch.on_experience_recorded(
            text="t", task="task", tools=["w1"], success=True
        )
        assert result["success"] is True


class TestPostChatPassesAgentCrystallizer:
    """post_chat Step9 → facade 必须透传 agent 自己的结晶器"""

    @pytest.mark.asyncio
    async def test_step9_passes_agent_crystallizer(self):
        from unittest.mock import MagicMock as MM

        from neurova.post_chat_pipeline import PostChatPipeline

        cryst = MM()
        agent = MM()
        agent.config.agent_id = "default"
        agent._collect_tool_messages.return_value = [
            {"tool_name": "w1", "success": True}
        ]
        agent.crystallizer = cryst

        pipeline = PostChatPipeline(agent)
        evolution = MM()
        pipeline._evolution = evolution

        await pipeline._step_record_experience(
            user_input="q", reply="r", save_memory=True
        )
        kwargs = evolution.on_experience_recorded.call_args.kwargs
        assert kwargs.get("crystallizer") is cryst, (
            "Step9 必须显式传 agent 自己的结晶器（agent 级隔离）"
        )
