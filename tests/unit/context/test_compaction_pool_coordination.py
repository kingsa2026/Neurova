"""
压缩 × 活水池配合的对话连续性闭环（2026-09-10，zcode 对齐终验）

用户问题：「上下文压缩与上下文活水池召回是否能相互配合，确保对话的连续性？」

四环闭环（缺一环 = 对话断片）：
1. 折叠——窗口超预算时老消息折叠为摘要行（修2）
2. 归档——折叠发生在 _archive_conversation_to_pool 之后（原文零丢失）
3. 召回——被折叠消息不在窗口 hash 集内，pool.draw 可按语义召回 [历史回忆]
4. 驻留——摘要行跨轮驻留窗口头部（增量防抖下不重复调摘要 LLM）

本测试组装 1→4 全链路：同一 orchestrator 连续多轮 build_context，验证
被折叠消息在后续轮次可被召回且摘要持续驻留。
"""
import pytest
from unittest.mock import MagicMock

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context_pool import ContextSource, ContextInput


def _mk_orchestrator(budget: int = 6000):
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
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    return orch


async def _build(orch, session_context, user_input="查询"):
    from unittest.mock import AsyncMock, patch

    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=session_context,
            relevant_memories=[],
        )


def _long(i, chars=800):
    return {"role": "user", "content": f"关于项目{chr(65 + i)}的长讨论{i}: " + "测" * chars}


class TestCompactionPoolCoordination:
    """折叠→归档→召回→驻留 四环闭环。"""

    @pytest.mark.asyncio
    async def test_archived_after_fold(self):
        """环1+2：折叠发生且原文已归档（hash 在归档集）。"""
        orch = _mk_orchestrator()
        ctx = [_long(i) for i in range(20)]
        result = await _build(orch, ctx)

        from neurova.context.window_compactor import estimate_window_tokens

        # 折叠确实发生（窗口 < 原始）
        window_tokens = estimate_window_tokens(
            [m for m in result if not str(m.get("content", "")).startswith(("[记忆]", "[经验]", "[历史回忆]"))]
        )
        assert window_tokens < estimate_window_tokens(ctx)
        # 归档集含被折叠的首条
        old_hash = ContextInput.compute_hash(ContextSource.CONVERSATION, ctx[0]["content"])
        assert old_hash in orch._last_archived_window_hashes

    @pytest.mark.asyncio
    async def test_folded_message_recallable(self):
        """环3：被折叠消息可经 pool.draw 语义召回（[历史回忆] 注入）。"""
        orch = _mk_orchestrator(budget=2500)
        # 每条消息独立关键词（0-11 号城市），折叠必然吞掉头部（0-5 号城市）
        ctx = [
            {
                "role": "user",
                "content": (
                    f"我们讨论了{i}号城市的部署方案，包括数据库迁移和灰度发布策略，"
                    f"目标是下季度完成切换{i}。补充说明{i}。" * 30
                ),
            }
            for i in range(12)
        ]
        _ = await _build(orch, ctx, user_input="12号城市")

        # 第二轮：查询指向**被折叠的** 0 号城市内容（窗口滑走、不在窗口 hash 集）
        ctx2 = ctx[6:] + [{"role": "user", "content": "0号城市部署的结论是什么？"}]
        result2 = await _build(orch, ctx2, user_input="0号城市部署的结论是什么？")

        joined = "".join(str(m.get("content", "")) for m in result2)
        # 被折叠的「0号城市…」经 [历史回忆] 召回（零丢失语义）
        assert "[历史回忆]" in joined, "折叠消息应可被 draw 语义召回"
        assert "0号城市" in joined

    @pytest.mark.asyncio
    async def test_summary_persists_across_turns(self):
        """环4：摘要行跨轮驻留窗口头部（第二次折叠复用缓存摘要）。"""
        orch = _mk_orchestrator()

        calls = {"n": 0}

        async def counting_summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return "摘要：早期讨论了项目A至项目T。"

        orch._window_summarizer = counting_summarize
        ctx = [_long(i) for i in range(20)]
        r1 = await _build(orch, ctx)
        joined1 = "".join(str(m.get("content", "")) for m in r1)
        assert "[早期对话摘要]" in joined1

        # 第二轮（小增量）：摘要继续驻留，且不重调摘要 LLM
        ctx2 = ctx + [{"role": "user", "content": "新话題X"}]
        r2 = await _build(orch, ctx2)
        joined2 = "".join(str(m.get("content", "")) for m in r2)
        assert "[早期对话摘要]" in joined2
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_no_recall_duplication_of_window(self):
        """配合防重：窗口已有内容不会被 draw 二次召回注入。"""
        orch = _mk_orchestrator(budget=6000)
        ctx = [_long(i) for i in range(6)]  # 预算内，全窗口保留
        result = await _build(orch, ctx, user_input="关于项目A的长讨论0")

        recall_lines = [
            str(m.get("content", "")) for m in result
            if str(m.get("content", "")).startswith("[历史回忆]")
        ]
        assert recall_lines == [], "窗口内消息不得被 draw 二次召回（injected_hashes 过滤）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
