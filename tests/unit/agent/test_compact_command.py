"""
/compact 手动压缩命令（2026-09-09，对齐 zcode）

语义：用户在会话里输入 /compact → 不调 LLM 正文轮，直接对当前会话
执行窗口压缩：
1. 触发 ContextOrchestrator 的窗口折叠（复用修2 的预算切分+摘要桥），
   并把折叠摘要写入跨轮缓存（后续轮次头部携带）；
2. 回复压缩报告（折叠条数/节省 token/池归档确认），跳过 LLM（B4 同款
   ctx.metadata["command_dispatched"] 短路）；
3. 无池/无历史/未超预算时给出明确说明，不报错。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


def _long_history(n=30):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"消息{i}: " + "测" * 500}
        for i in range(n)
    ]


def _mk_pipeline(manual_compact=None):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "a1"
    agent.config.name = "t"
    agent.agent_id = "a1"
    agent.user_id = "u1"
    agent.memory_agent = MagicMock()
    agent.tool_memory = None
    agent.skill_manager = None
    agent._skill_registry = MagicMock()
    agent._skill_registry.has_skill = MagicMock(return_value=False)
    pipe = ChatPipeline(agent)
    # 桩 ContextOrchestrator（property 直通 agent）：只测命令层的分发与短路语义
    agent.context_orchestrator = MagicMock()
    agent.context_orchestrator.manual_compact = manual_compact or AsyncMock(
        return_value={"compacted": True, "folded": 24, "kept": 6,
                      "tokens_before": 20000, "tokens_after": 4200,
                      "summary_generated": True}
    )
    return pipe, agent


class TestCompactCommand:
    @pytest.mark.asyncio
    async def test_compact_invokes_manual_compact_and_short_circuits_llm(self):
        pipe, agent = _mk_pipeline()
        ctx = ChatContext(user_input="/compact")
        ctx.session_id = "s1"

        await pipe._check_compact_command(ctx)

        agent.context_orchestrator.manual_compact.assert_awaited_once()
        assert ctx.metadata.get("command_dispatched") is True
        assert "24" in ctx.reply  # 折叠条数出现在报告里

    @pytest.mark.asyncio
    async def test_compact_with_args_still_works(self):
        """/compact [提示] 形态兼容（参数仅作为摘要侧重点提示，不报错）。"""
        pipe, _ = _mk_pipeline()
        ctx = ChatContext(user_input="/compact 重点保留项目决策")
        ctx.session_id = "s1"

        await pipe._check_compact_command(ctx)
        assert ctx.metadata.get("command_dispatched") is True

    @pytest.mark.asyncio
    async def test_non_compact_input_ignored(self):
        pipe, agent = _mk_pipeline()
        ctx = ChatContext(user_input="/help 我要压缩")
        await pipe._check_compact_command(ctx)
        agent.context_orchestrator.manual_compact.assert_not_awaited()
        assert not (ctx.metadata or {}).get("command_dispatched")

    @pytest.mark.asyncio
    async def test_compact_failure_falls_through(self):
        """manual_compact 异常 → 不短路，回落正常 LLM 流程（不崩轮）。"""
        pipe, agent = _mk_pipeline(
            manual_compact=AsyncMock(side_effect=RuntimeError("boom"))
        )
        ctx = ChatContext(user_input="/compact")
        ctx.session_id = "s1"

        await pipe._check_compact_command(ctx)
        assert not (ctx.metadata or {}).get("command_dispatched")

    @pytest.mark.asyncio
    async def test_compact_reports_noop_when_not_oversized(self):
        pipe, agent = _mk_pipeline(
            manual_compact=AsyncMock(
                return_value={"compacted": False, "folded": 0, "kept": 4,
                              "tokens_before": 900, "tokens_after": 900,
                              "summary_generated": False}
            )
        )
        ctx = ChatContext(user_input="/compact")
        ctx.session_id = "s1"

        await pipe._check_compact_command(ctx)
        assert ctx.metadata.get("command_dispatched") is True
        assert "无需" in ctx.reply or "未超" in ctx.reply

    @pytest.mark.asyncio
    async def test_compact_emits_reply_to_sse_emitter(self):
        """/compact 无 LLM content 事件——回复必须经 event_emitter 直达 SSE 客户端。"""
        pipe, agent = _mk_pipeline()
        emitted = []
        ctx = ChatContext(user_input="/compact")
        ctx.session_id = "s1"
        # emitter 契约 = _emit(kind, data) 双参（console 端点定义）
        ctx.metadata = {"event_emitter": lambda kind, data: emitted.append((kind, data))}

        await pipe._check_compact_command(ctx)

        assert emitted, "命令回复必须发射到 event_emitter（SSE 客户端可见）"
        kinds = [k for k, _ in emitted]
        assert "content" in kinds
        texts = "".join(d for k, d in emitted if k == "content")
        assert "压缩" in texts


class TestManualCompact:
    """orchestrator.manual_compact 本体：强制折叠 + 摘要落缓存。"""

    def _mk_orchestrator(self):
        from neurova.context.orchestrator import ContextOrchestrator

        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.name = "t"
        agent.config.constitution = ""
        agent.config.behavior_rules = []
        agent.config.llm_model = "test-model"
        agent.memory_manager = MagicMock()
        agent.context_builder = MagicMock()
        agent.tool_router = None
        agent._skill_registry = None
        agent.soul = "测试soul"
        agent.personality = ""
        agent.conversation_history = []
        agent.growth_log_manager = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"
        # 摘要桥用真 LLM 通道（SummarizingCompressor → agent.llm_client.chat），
        # 给可用桥以覆盖「摘要落缓存」的真实契约
        agent.llm_client = MagicMock()
        agent.llm_client.chat = AsyncMock(return_value={"content": "测试摘要：会话讨论了30条长消息。"})
        orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
        # 强制小预算，保证历史必然超限
        orch._force_window_budget = 4000
        return orch

    @pytest.mark.asyncio
    async def test_manual_compact_forces_fold_and_caches_summary(self):
        orch = self._mk_orchestrator()
        orch.set_session_id("sess-mc")
        history = _long_history()

        result = await orch.manual_compact(history)

        assert result["compacted"] is True
        assert result["folded"] > 0
        # 摘要进了跨轮缓存：下轮 build_context 折叠时携带同一摘要
        cache = orch._window_compaction_cache.get("sess-mc")
        assert cache and cache.get("summary")

    @pytest.mark.asyncio
    async def test_manual_compact_noop_under_budget(self):
        orch = self._mk_orchestrator()
        orch.set_session_id("sess-mc2")
        result = await orch.manual_compact(
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        )
        assert result["compacted"] is False

    @pytest.mark.asyncio
    async def test_manual_compact_empty_history(self):
        orch = self._mk_orchestrator()
        result = await orch.manual_compact([])
        assert result["compacted"] is False
        assert result.get("reason") == "empty_history"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
