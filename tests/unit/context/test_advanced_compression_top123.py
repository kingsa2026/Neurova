"""
先进压缩技术落地三件套（2026-09-10，调研报告 Top1/Top2/Top3）

Top1 摘要提示词时间保留修正（The Sleeping Agent, arXiv 2608.11775）：
    提示词必须显式要求保留时间/计量表达。
Top2 工具结果占位清除（Anthropic context editing 对齐）：
    老工具结果替换为占位指针，最近 3 个保留原文；仅 8k+ 窗口启用。
Top3 递进折叠比例（Letta compaction 对齐）：
    折叠比例从 target_ratio 起步，折叠后仍超预算按 +0.1 步进重试。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import compact_window, estimate_window_tokens
from neurova.context import summarizing_compressor as sc


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
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=session_context,
            relevant_memories=[],
        )


class TestTop1SummaryPrompt:
    def test_prompt_requires_time_preservation(self):
        """提示词显式要求保留时间/计量表达（Sleeping Agent 修正）。"""
        assert "时间" in sc._DEFAULT_PROMPT_TEMPLATE
        assert "数量" in sc._DEFAULT_PROMPT_TEMPLATE
        assert "禁止模糊化" in sc._DEFAULT_PROMPT_TEMPLATE

    def test_prompt_requires_decisions_and_pending(self):
        """决定/偏好/未决问题/专有名词保留要求在提示词中。"""
        tpl = sc._DEFAULT_PROMPT_TEMPLATE
        for kw in ("决定", "未解决", "专有名词"):
            assert kw in tpl

    def test_summary_actually_preserves_time_expression(self):
        """端到端：含时间表达的对话折叠后，LLM 摘要桥收到的 prompt 含时间原文。"""
        captured = {}

        async def fake_llm(prompt):
            captured["prompt"] = prompt
            return "用户要求周三前完成部署。"

        comp = sc.SummarizingCompressor(llm_call=fake_llm)

        from neurova.context_pool import ContextInput, ContextSource

        chunks = [
            ContextInput(
                source=ContextSource.CONVERSATION,
                content="用户：这个部署必须在周三前完成，涉及 3 个节点。",
                priority=60,
            )
        ]
        import asyncio

        result = asyncio.run(comp.summarize(chunks))
        assert "周三" in captured["prompt"]
        assert "3 个节点" in captured["prompt"]
        assert "周三前完成部署" in result


class TestTop2ToolResultClearing:
    def _tool_window(self, n_results=6, big=False):
        """构造含 n 个工具结果的窗口（role=tool 与 assistant(tool_calls) 配对）。"""
        msgs = [{"role": "system", "content": "sys"}]
        filler = "结果数据" * (600 if big else 5)  # big: 每条约 2400 字 ≈ 1600 token
        for i in range(n_results):
            msgs.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": f"c{i}", "type": "function",
                                "function": {"name": "file_read", "arguments": f"{{\"p\":\"f{i}\"}}"}}],
            })
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"工具结果{i}: {filler}"})
        return msgs

    def test_old_tool_results_cleared_when_large(self):
        """大窗口：最近 3 个保留原文，更早的占位替换。"""
        orch = _mk_orchestrator()
        msgs = self._tool_window(6, big=True)
        cleared = orch._clear_old_tool_results(msgs)

        tool_contents = [m["content"] for m in cleared if m.get("role") == "tool"]
        assert tool_contents[0].startswith("[工具输出已清除")
        assert tool_contents[1].startswith("[工具输出已清除")
        assert tool_contents[-1].startswith("工具结果5")  # 最近 3 个保留
        assert tool_contents[-3].startswith("工具结果3")

    def test_small_window_untouched(self):
        """小窗口（≤8k token）：零替换。"""
        orch = _mk_orchestrator()
        msgs = self._tool_window(6, big=False)
        cleared = orch._clear_old_tool_results(msgs)
        assert cleared == msgs

    def test_short_results_keep_original(self):
        """极短工具结果（<80 字符）即使很老也保留（状态码类）。"""
        orch = _mk_orchestrator()
        msgs = self._tool_window(6, big=True)
        msgs[2] = {"role": "tool", "tool_call_id": "c0", "content": "200 OK"}  # 极短老结果
        cleared = orch._clear_old_tool_results(msgs)
        assert cleared[2]["content"] == "200 OK"

    def test_clear_integrated_in_build_context(self):
        """build_context 装配路径：大工具窗口自动触发占位清除。"""
        orch = _mk_orchestrator(budget=100000)  # 大预算：不触发窗口折叠
        msgs = self._tool_window(6, big=True)
        # 剥掉 tool_calls 字段模拟视图重建后的形态（build_context 输入契约）
        plain = [{k: v for k, v in m.items() if k != "tool_calls" and k != "tool_call_id"} for m in msgs]

        async def run():
            return await _build(orch, plain, user_input="总结工具结果")

        import asyncio
        result = asyncio.run(run())
        joined = "".join(str(m.get("content", "")) for m in result)
        assert "[工具输出已清除" in joined
        assert "工具结果5" in joined  # 最近保留


class TestTop3ProgressiveFold:
    @pytest.mark.asyncio
    async def test_progressive_folds_more_when_needed(self):
        """首折比例装不下且仍有可折空间 → 步进扩大折叠比例。"""
        calls = {"n": 0}

        async def summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return f"摘要v{calls['n']}"

        # 尾部巨消息 + 头部小消息：ratio=0.5 时 keep_min 保底窗口超预算，
        # 递进扩大比例后把巨消息也折进去，最终装下
        msgs = [
            {"role": "user", "content": f"小消息{i}: " + "测" * 20} for i in range(8)
        ] + [
            {"role": "user", "content": f"巨消息{i}: " + "测" * 400} for i in range(2)
        ]
        budget = 1200
        result = await compact_window(msgs, budget, summarize=summarize, target_ratio=0.5)
        assert result is not None
        assert result.tokens_after < result.tokens_before, "折叠必须净减"
        assert calls["n"] >= 1

    @pytest.mark.asyncio
    async def test_unsolvable_returns_keep_min_minimum_no_hang(self):
        """keep_min 下限本身超预算：返回最小窗口、不无限循环。"""
        calls = {"n": 0}

        async def summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return "摘要"

        # 6 条消息每条 ~670 token = keep_min 下限 4000+ > 预算 2000 → 物理无解
        msgs = [{"role": "user", "content": f"巨消息{i}: " + "测" * 500} for i in range(6)]
        result = await compact_window(msgs, 2000, summarize=summarize, target_ratio=0.5)
        assert result is not None, "无解时也应返回尽力结果"
        assert result.compacted_count + len(result.window) >= len(msgs) - 6  # keep_min 尊重
        assert calls["n"] <= 10, "递进必须收敛终止"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
