"""
修2（2026-09-09）：对话窗口 token 预算 + 超限自动压缩（zcode 式）

根因：get_recent_context 是固定 20 条消息数窗口、build_context 的
window_msgs 全量进视图——两者均无 token 预算。kai 3.5 万 token prompt
事故中对话窗口虽只占 1k token，但该缺口使长对话/长工具结果必然撑爆
prompt（有池也拦不住，池是归档+召回不裁剪）。

契约：
1. ContextOrchestrator.build_context 对窗口做 token 预算裁剪——预算取
   get_token_budget_for_model（模型元数据×0.6），从尾部保留，超出部分
   经 SummarizingCompressor 生成摘要（或降级为静态折叠桩）注入窗口头部；
   原文已归档池中（_archive_conversation_to_pool 在裁剪之前执行，零丢失）。
2. 折叠后的摘要注入位置必须在系统前缀之后、近期窗口之前，以 system 角色出现。
3. 窗口未超预算时零行为变化（不注入摘要桩）。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.context.orchestrator import ContextOrchestrator


def _mk_agent(model: str = "test-model"):
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.llm_model = model
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u1"
    mock_agent.agent_id = "a1"
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    """单条约 600 token 的消息（中文按 1.5 char/token 平衡策略估算）。"""
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


class TestWindowTokenBudget:
    """对话窗口 token 预算裁剪。"""

    def _mk_orchestrator(self, model: str = "test-model", budget: int = 8000):
        agent = _mk_agent(model)
        orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
        # 固定预算（脱离 provider 元数据，测试确定性）
        orch._window_token_budget = budget
        return orch

    async def _build(self, orch, session_context):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            return await orch.build_context(
                user_input="你好",
                session_context=session_context,
                relevant_memories=[],
            )

    @pytest.mark.asyncio
    async def test_small_window_unchanged(self):
        """未超预算：零行为变化，不出现摘要桩。"""
        orch = self._mk_orchestrator(budget=8000)
        ctx = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = await self._build(orch, ctx)
        joined = "".join(m["content"] for m in result)
        assert "hi" in joined and "hello" in joined
        assert "[早期对话摘要]" not in joined and "已折叠" not in joined

    @pytest.mark.asyncio
    async def test_oversized_window_folded(self):
        """超预算：老消息被折叠，尾部窗口保留，摘要桩出现。"""
        orch = self._mk_orchestrator(budget=8000)
        ctx = [_long_msg(i) for i in range(30)]  # ≈18000 token > 8000
        result = await self._build(orch, ctx)

        contents = [m["content"] for m in result]
        joined = "".join(contents)

        # 尾部近期消息必须保留（最后 2 条在预算内）
        assert "长消息29" in joined and "长消息28" in joined
        # 早期消息大部分被折叠
        assert "长消息0" not in joined
        # 出现折叠桩（静态摘要或 LLM 摘要形态均可，stub 摘要器时为静态桩）
        stubs = [m for m in result if "[早期对话摘要]" in m["content"]]
        assert stubs and all(m["role"] == "system" for m in stubs)

    @pytest.mark.asyncio
    async def test_folded_messages_still_archived_to_pool(self):
        """裁剪发生在归档之后：被折叠消息已进池（零丢失），可被语义召回。"""
        orch = self._mk_orchestrator(budget=8000)
        ctx = [_long_msg(i) for i in range(30)]
        result = await self._build(orch, ctx)

        hashes = orch._last_archived_window_hashes
        assert hashes, "折叠前应完成归档"
        # 折叠掉的老消息 hash 在归档集合中
        from neurova.context_pool import ContextInput, ContextSource

        old_hash = ContextInput.compute_hash(ContextSource.CONVERSATION, ctx[0]["content"])
        assert old_hash in hashes

    @pytest.mark.asyncio
    async def test_llm_summary_replaces_stub_when_available(self):
        """摘要器可用时：注入真摘要而非静态桩。"""
        orch = self._mk_orchestrator(budget=8000)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：用户讨论了30条长消息的主题X。"

        orch._window_summarizer = fake_summarize
        ctx = [_long_msg(i) for i in range(30)]
        result = await self._build(orch, ctx)

        joined = "".join(m["content"] for m in result)
        assert "主题X" in joined
        assert "长消息0" not in joined

    @pytest.mark.asyncio
    async def test_budget_defaults_from_model_metadata(self):
        """未显式指定预算时：从 get_token_budget_for_model 解析（不崩溃）。"""
        orch = self._mk_orchestrator(model="glm-5.3-flash")
        # _window_token_budget 未设置 → 应有解析出的默认值且为正
        assert orch._resolve_window_token_budget() > 0

    @pytest.mark.asyncio
    async def test_small_delta_reuses_cached_summary_without_llm(self):
        """稳态防抖：折叠区仅小增量新消息时不重调摘要 LLM（复用缓存摘要）。"""
        orch = self._mk_orchestrator(budget=8000)
        calls = {"n": 0}

        async def counting_summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return f"摘要v{calls['n']}：历史讨论持续。"

        orch._window_summarizer = counting_summarize
        ctx = [_long_msg(i) for i in range(30)]
        r1 = await self._build(orch, ctx)
        assert calls["n"] == 1

        # 第二轮：尾部追加 2 条短消息（原 kept 头部 2 条滑入折叠区，增量 < 阈值）
        ctx2 = ctx + [
            {"role": "user", "content": "短问题一"},
            {"role": "assistant", "content": "短回答一"},
        ]
        r2 = await self._build(orch, ctx2)
        assert calls["n"] == 1, "小增量不应触发第二次摘要 LLM 调用"
        joined2 = "".join(m["content"] for m in r2)
        assert "摘要v1" in joined2, "应复用既有缓存摘要"

    @pytest.mark.asyncio
    async def test_accumulated_delta_retriggers_summary(self):
        """增量累积超阈值后：重新摘要（覆盖新滑入的消息）。"""
        orch = self._mk_orchestrator(budget=8000)
        calls = {"n": 0}

        async def counting_summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return f"摘要v{calls['n']}：历史讨论持续。"

        orch._window_summarizer = counting_summarize
        ctx = [_long_msg(i) for i in range(30)]
        _ = await self._build(orch, ctx)
        assert calls["n"] == 1

        # 追加 6 条短消息（累计增量 ≥ 阈值 250 token）→ 重新摘要
        for j in range(3):
            ctx = ctx + [
                {"role": "user", "content": f"短问题{j}a"},
                {"role": "assistant", "content": f"短回答{j}b"},
            ]
        r3 = await self._build(orch, ctx)
        assert calls["n"] == 2, "累计增量超阈值应重新摘要"
        joined3 = "".join(m["content"] for m in r3)
        assert "摘要v2" in joined3
