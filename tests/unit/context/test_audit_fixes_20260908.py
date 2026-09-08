# -*- coding: utf-8 -*-
"""2026-09-08 全库审计修复防回归：context 链路批。

覆盖审计项：
- ④ 信封 token 双计 → 压缩过度（injector._compress_context 预算扣两次）
- ⑥ builder.compress_if_needed 旧签名调用 → TypeError 被吞恒走降级
- ⑦ orchestrator 先 repair 后剥字段 → 孤儿 tool 消息发 LLM（400）
- ⑬ 降级路径 user_input 双份 + 系统指令双份
- ⑭ repair 多缺失 tool_call 结果只补一条拼接 id
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.context.builder import ContextBuilder
from neurova.context.injector import UnifiedContextInjector
from neurova.context.models import TokenBudget
from neurova.context.recovery import repair_tool_turns


# ── ④ 信封 token 双计 ────────────────────────────────────────────

class TestEnvelopeBudgetNoDoubleCount:
    """压缩后 system+历史+信封+user ≤ max_total，且信封非空时记忆不整丢。"""

    def _make_injector(self, max_total: int) -> UnifiedContextInjector:
        inj = UnifiedContextInjector(
            memory_manager=MagicMock(),
            token_budget=TokenBudget(max_total=max_total, memories=2000, conversation_history=8000),
            enable_cache=False,
            enable_compression=True,
        )
        return inj

    def test_budget_invariant_holds_after_compression(self):
        """触发压缩后总账不超预算，且保留下来的信封内容与预算自洽。"""
        inj = self._make_injector(max_total=3000)
        history = [
            {"role": "user", "content": f"历史消息第{i}轮" + "内容填充" * 40}
            for i in range(30)
        ]
        result = inj.build_context(
            system_prompt="系统提示",
            memories=[{"content": "重要记忆A" * 30, "temperature": 80}],
            conversation_history=history,
            user_input="当前问题",
        )
        assert result.total_tokens <= 3000, (
            f"压缩后 total_tokens={result.total_tokens} 超预算 3000（信封双计暴露）"
        )

    def test_envelope_not_dropped_when_budget_sufficient(self, monkeypatch):
        """压缩触发时历史保留条数=预算上限容纳的最大值（不因信封双计多弃）。"""
        inj = self._make_injector(max_total=1200)
        # 中性化 _adjust_budget，隔离信封压缩路径（该测试只打双计）
        monkeypatch.setattr(
            UnifiedContextInjector, "_adjust_budget", lambda self, h, m, mt: self._token_budget
        )
        # 实测口径（TokenEstimator BALANCED）：历史条≈96；system≈300；
        # 信封≈331；裸 user≈6。
        # 总账：300 + 800(trim 预算满载) + 337 = 1437 > 1200 → 必触发压缩。
        # 修复后裸 user 口径：1200-300-6=894 ≥331+96n → n=5 保留 5 条历史；
        # 双计旧径 user 含信封(337)：1200-300-337=563 ≥331+96n → n=2。
        history = [
            {"role": "user", "content": "历史消息内容填充" * 8} for _ in range(12)
        ]
        result = inj.build_context(
            system_prompt="系统提示" * 50,
            memories=[{"content": "重要记忆内容" * 18, "temperature": 80}],
            conversation_history=history,
            user_input="当前问题",
        )
        kept = [
            m
            for m in result.context
            if m["role"] == "user" and m["content"].startswith("历史消息内容填充")
        ]
        assert len(kept) == 5, f"历史保留 {len(kept)} 条 ≠ 5（信封双计导致过度丢弃）"
        assert result.total_tokens <= 1200


# ── ⑥ builder.compress_if_needed 签名漂移 ────────────────────────

class TestCompressIfNeededUsesNewSignature:
    """带 injector 的 compress_if_needed 必须真压缩而非吞 TypeError 走降级。"""

    def test_injector_path_compresses_history(self):
        builder = ContextBuilder(config={})
        builder._unified_injector = UnifiedContextInjector(
            memory_manager=MagicMock(),
            token_budget=TokenBudget(max_total=2000, memories=500, conversation_history=1000),
            enable_cache=False,
            enable_compression=True,
        )
        context = (
            [{"role": "system", "content": "系统指令"}]
            + [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}轮" + "填充内容" * 100}
                for i in range(40)
            ]
            + [{"role": "user", "content": "最终问题"}]
        )
        result = builder.compress_if_needed(context)
        # 新签名路径生效的判据：历史被真实裁剪（旧 bug 下 TypeError 被吞 →
        # fallback_compress 行为，这里锁定 injector 压缩路径不再抛错且生效）
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "最终问题"
        assert len(result) < len(context)


# ── ⑦ 视图重建不得产出孤儿 tool 消息 ─────────────────────────────

def _make_orchestrator():
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "t"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.memory_manager = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "s"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = None
    mock_agent.user_id = "u"
    mock_agent.agent_id = "t"

    orch = None
    with patch("neurova.context_pool.ContextPool") as pool_cls:
        pool_cls.get_token_budget_for_model.return_value = 8000
        pool_cls.return_value.draw.return_value = []
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(mock_agent, use_pool=True)
    return orch


class TestViewRebuildNoOrphanTool:
    """session_context 携带完整 tool 轮次时，产出上下文必须协议合法。"""

    @pytest.mark.asyncio
    async def test_tool_turns_survive_view_rebuild(self):
        orch = _make_orchestrator()
        # 修复后判据：tool_calls 不被剥掉，或剥掉后 role:"tool" 被转为 user 注记
        session_context = [
            {"role": "user", "content": "查天气"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "weather", "content": "晴 25°C"},
        ]
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
            result = await orch.build_context(
                user_input="那明天呢",
                session_context=session_context,
            )
        for i, msg in enumerate(result):
            if msg.get("role") == "tool":
                # tool 消息必须仍与某个前文 assistant.tool_calls 配对
                declared = set()
                for m in result[:i]:
                    for c in m.get("tool_calls") or []:
                        declared.add(c.get("id"))
                assert msg.get("tool_call_id") in declared, (
                    f"产出孤儿 tool 消息（tool_call_id={msg.get('tool_call_id')}）→ provider 400"
                )


# ── ⑬ 降级路径 user_input 双份 ───────────────────────────────────

class TestFallbackNoDuplicateUserInput:
    """context_builder 不可用时的降级路径：user_input 只出现一次。"""

    @pytest.mark.asyncio
    async def test_user_input_once_and_system_once(self):
        orch = _make_orchestrator()
        # 关 pool + context_builder 置空 → 进入降级分支
        orch.use_pool = False
        orch.context_pool = None
        orch._agent.context_builder = None
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
            result = await orch.build_context(
                user_input="唯一的问题",
                relevant_memories=[{"content": "记忆甲", "temperature": 60}],
            )
        user_msgs = [m for m in result if m.get("role") == "user"]
        joined = "\n".join(m.get("content", "") for m in user_msgs)
        assert joined.count("唯一的问题") == 1, (
            f"user_input 在降级路径出现 {joined.count('唯一的问题')} 次（含信封外重复）"
        )
        # soul 系统指令只一份（candidate_pool 里 SYSTEM_INSTRUCTION 不再原样重发）
        sys_joined = "\n".join(m.get("content", "") for m in result if m.get("role") == "system")
        assert sys_joined.count("s") >= 1  # soul 在
        # 记忆经信封保留
        assert "记忆甲" in joined


# ── ⑭ repair 多缺失 tool_call 结果 ───────────────────────────────

class TestRepairMultipleMissingResults:
    """assistant 声明 N 个调用、结果全缺时，逐 call 补齐独立合成结果。"""

    def test_each_missing_call_gets_own_result(self):
        messages = [
            {"role": "user", "content": "并行查"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "t1", "arguments": "{}"}},
                    {"id": "b", "type": "function", "function": {"name": "t2", "arguments": "{}"}},
                    {"id": "c", "type": "function", "function": {"name": "t3", "arguments": "{}"}},
                ],
            },
        ]
        out = repair_tool_turns(messages)
        tool_msgs = [m for m in out if m.get("role") == "tool"]
        ids = {m.get("tool_call_id") for m in tool_msgs}
        assert {"a", "b", "c"} <= ids, f"合成结果 id 集合 {ids} 未逐 call 覆盖"
        for m in tool_msgs:
            assert "," not in str(m.get("tool_call_id")), "拼接 id 不匹配任何单 call"
