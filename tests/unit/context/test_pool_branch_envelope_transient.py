# -*- coding: utf-8 -*-
"""B3 剩余 P2-8（D4 甲案）：pool 分支的瞬态注入一律收回末条 user 信封。

根因（三链路审计 P2-8 + §10 D4 裁决记录）：pool 分支把记忆/经验/结晶/待探索问题/
池召回/工具记忆/情感七类**动态检索文本**以 `role="system"` 行直注——它们
①不受任何 token 预算管辖（窗口预算只覆盖对话消息），②落在免疫句覆盖范围之外
（`system` 角色权重最高且无隔离声明）。D4 采纳甲案：全部瞬态注入收回末条 user
消息的 `<system-reminder>` 信封，并**接入 `compress_envelope`**。

三条不可省略的前置条件（审计原文，缺一条甲案就退化为"只换位置"）：

1. pool 分支必须接入 `compress_envelope`——否则内容换位置后仍不受预算管辖；
2. 范围必须一次做全（七处注入位无 `system` 行残留），半接状态比不改更糟；
3. 新增 `<history>`（池召回）与 `<tooling>`（工具记忆/待探索问题）两块，
   并定淘汰顺位（`<history>` 紧跟 `emotion` 之后：它是原文，池内无损可再召回）。

防回归纪律：走**生产构造面**（`agent_core` 那条调用形状），预算只经既有的
`_window_token_budget` 测试钩子注入，不手工赋私有字段。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.envelope import COMPRESS_DROP_ORDER, build_envelope, parse_envelope


def _agent(**overrides):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
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
    agent.question_queue_manager = None
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def _orchestrator(budget: int | None = None):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    if budget is not None:
        orch._window_token_budget = budget
    return orch


async def _build(orch, **kwargs):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(**kwargs)


def _envelopeOf(result):
    """末条 user 消息里的信封块（无信封返回空 dict）。"""
    return parse_envelope(str((result[-1] or {}).get("content", "")))


def _systemJoined(result) -> str:
    return "\n".join(str(m.get("content", "")) for m in result if m.get("role") == "system")


class TestTransientInjectionsLandInTheEnvelope:
    """七处注入位一次做全：全部落进末条 user 信封，system 段无残留。"""

    @pytest.mark.asyncio
    async def test_retrievalProductsAreNotSystemRows(self):
        orch = _orchestrator()
        result = await _build(
            orch,
            user_input="帮我看看部署方案",
            relevant_memories=[{"content": "用户偏好灰度发布"}],
            experience_items=[{"content": "先备份再迁移", "id": "e1"}],
            crystallized_patterns=[{"content": "迁移前先冻结写入"}],
            session_context=[{"role": "user", "content": "讨论迁移"}],
        )

        blocks = _envelopeOf(result)
        assert blocks, "末条 user 消息没有信封——瞬态注入未收回信封"
        assert "用户偏好灰度发布" in blocks.get("memories", "")
        assert "先备份再迁移" in blocks.get("experience", "")
        assert "迁移前先冻结写入" in blocks.get("experience", "")

        sys_joined = _systemJoined(result)
        for leaked in ("用户偏好灰度发布", "先备份再迁移", "迁移前先冻结写入"):
            assert leaked not in sys_joined, f"检索文本仍以 system 行直注：{leaked}"

    @pytest.mark.asyncio
    async def test_toolMemoryAndPendingQuestionsUseToolingBlock(self):
        questions = MagicMock()
        q = MagicMock()
        q.id = "q1"
        q.content = "要不要顺手加个回滚脚本？"
        questions.get_pending_questions.return_value = [q]
        questions.mark_asked = MagicMock()

        orch = _orchestrator()
        orch._agent.question_queue_manager = questions
        result = await _build(
            orch,
            user_input="继续",
            tool_memory_result={"tool_name": "file_read", "result": "4096 bytes"},
        )

        tooling = _envelopeOf(result).get("tooling", "")
        assert "[工具记忆]" in tooling and "file_read" in tooling
        assert "回滚脚本" in tooling
        assert "[工具记忆]" not in _systemJoined(result)
        assert "回滚脚本" not in _systemJoined(result)

    @pytest.mark.asyncio
    async def test_recalledHistoryUsesHistoryBlock(self):
        orch = _orchestrator()
        await _build(
            orch,
            user_input="我下周要去许昌出差",
            session_context=[{"role": "user", "content": "我下周要去许昌出差"}],
        )
        result = await _build(
            orch,
            user_input="还记得我要去哪里出差吗",
            session_context=[{"role": "user", "content": "今天心情不错"}],
        )

        blocks = _envelopeOf(result)
        assert "history" in blocks, "池召回块没有落到 <history>"
        assert "[历史回忆]" in blocks["history"]
        assert "许昌" in blocks["history"]
        assert "[历史回忆]" not in _systemJoined(result)

    @pytest.mark.asyncio
    async def test_emotionIsInTheEnvelopeNotSystem(self):
        orch = _orchestrator()
        result = await _build(orch, user_input="我今天很烦，不想干活")

        blocks = _envelopeOf(result)
        if "emotion" in blocks:
            assert "[情感]" in blocks["emotion"]
            assert "[情感]" not in _systemJoined(result)

    @pytest.mark.asyncio
    async def test_systemSectionKeepsOnlyTheFixedPrefix(self):
        """system 段只剩固定前缀（soul/personality/constitution），前缀缓存前提。"""
        orch = _orchestrator()
        r1 = await _build(
            orch,
            user_input="第一轮",
            relevant_memories=[{"content": "记忆甲"}],
        )
        r2 = await _build(
            orch,
            user_input="第二轮",
            relevant_memories=[{"content": "记忆乙"}],
        )
        systems = [m["content"] for m in r1 if m["role"] == "system"]
        assert systems == [m["content"] for m in r2 if m["role"] == "system"], (
            "system 段跨轮变化（动态注入泄漏进 system 会击穿前缀缓存）"
        )


class TestEnvelopeIsUnderBudgetControl:
    """前置条件 1：pool 分支接入 `compress_envelope`，信封受预算管辖。"""

    @pytest.mark.asyncio
    async def test_poolBranchPassesABudgetToCompressEnvelope(self):
        """前置条件 1 的可证伪形态：pool 分支真的调了 `compress_envelope` 并给了额度。

        只断言"信封变短了"是不够的——那可能来自任何别的原因。断言点是**调用本身**
        与**传入的额度**：不调就是不接预算管辖，额度为 0 就是把内容压成空串。
        """
        import neurova.context.envelope as envelopeModule

        seen = {}
        original = envelopeModule.compress_envelope

        def spy(envelope, budget_tokens, count_tokens=None):
            seen["budget"] = budget_tokens
            result = original(envelope, budget_tokens, count_tokens=count_tokens)
            seen["before"] = len(envelope)
            seen["after"] = len(result)
            return result

        orch = _orchestrator(budget=1200)
        bulky = "这是一条很长的记忆内容，用于撑爆信封预算。" * 40
        with patch.object(envelopeModule, "compress_envelope", side_effect=spy):
            result = await _build(
                orch,
                user_input="问题",
                relevant_memories=[{"content": bulky}],
                session_context=[{"role": "user", "content": "短历史" * 20}],
            )

        assert "budget" in seen, "pool 分支没有调用 compress_envelope——信封不受预算管辖"
        assert seen["budget"] >= orch._ENVELOPE_MIN_TOKENS, (
            f"信封额度 {seen['budget']} 低于地板，内容会被压成空串"
        )
        from neurova.context.token_estimator import estimate_tokens

        envelope = str(result[-1]["content"]).split("\n\n")[0]
        assert estimate_tokens(envelope) <= max(seen["budget"], orch._ENVELOPE_MIN_TOKENS), (
            "信封未被压回额度内（compress_envelope 的返回值未被采用）"
        )

    @pytest.mark.asyncio
    async def test_oversizedEnvelopeKeepsMemoriesAndBoundsTheBlock(self):
        """超预算时 memories 按行淘汰（不整包丢），且整段仍落在信封额度内。

        淘汰**顺位**由 `envelope.py` 单源声明，纯函数面已单独锁住
        （`test_largeEnvelopeDropsHistoryBeforeMemories`）；本用例锁 pool 分支
        这条装配链上的可观察结果。
        """
        orch = _orchestrator(budget=1200)
        bulky = "这是一条很长的记忆内容，用于撑爆信封预算。" * 200
        result = await _build(
            orch,
            user_input="帮我看看这个问题的上下文预算怎么算才合适",
            relevant_memories=[{"content": bulky}],
            session_context=[{"role": "user", "content": "短历史" * 20}],
        )
        envelope = str(result[-1]["content"]).split("\n\n")[0]
        blocks = parse_envelope(envelope)
        assert blocks, "信封被整包丢弃——memories 兜底块也丢了"
        assert "memories" in blocks, "memories 是唯一兜底块，必须保留头部"

        from neurova.context.token_estimator import estimate_tokens

        fixed = orch._envelopeFixedTokens(
            {k: (v or "").splitlines() for k, v in blocks.items() if k != "history"}
        )
        quota = max(
            orch._ENVELOPE_MIN_TOKENS,
            orch._resolve_window_token_budget()
            - estimate_tokens("帮我看看这个问题的上下文预算怎么算才合适")
            - fixed,
        )
        assert estimate_tokens(envelope) <= fixed + quota + 1, "信封未被压回额度内"

    @pytest.mark.asyncio
    async def test_envelopeIsBoundedByItsQuotaNotByTheWindow(self):
        """预算账目闭合：信封占用 ≤ 固定部分 + 撤回额度 + 前缀开销（单源额度）。

        口径如实：**视图总量不总 ≤ 视图预算**——窗口折叠有 `keep_min_messages`
        物理下限，折叠到下限仍超预算时窗口本身就在预算之外，这是既有语义、
        本片不改变。本片要钉的是"信封受自己那份额度管辖"，而不是它去背窗口的账。
        """
        from neurova.context.token_estimator import estimate_tokens
        from neurova.context.window_compactor import estimate_window_tokens

        orch = _orchestrator(budget=3000)
        bulky = "历史检索文本。" * 200
        history = [{"role": "user", "content": f"第{i}轮" + "测" * 200} for i in range(12)]
        result = await _build(
            orch,
            user_input="问题",
            relevant_memories=[{"content": bulky}] * 5,
            session_context=history,
        )

        from neurova.context.envelope import parse_envelope

        envelope = str(result[-1]["content"]).split("\n\n")[0]
        parsed = parse_envelope(envelope)
        # 固定部分以**信封自身实际渲染出的块**为准（不另猜一份口径）
        fixed = {
            tag: value for tag, value in parsed.items() if tag != "history"
        }
        quota = max(
            orch._ENVELOPE_MIN_TOKENS,
            orch._resolve_window_token_budget()
            - estimate_window_tokens(
                [m for m in result if m.get("role") in ("user", "assistant")][:-1]
            )
            - orch._envelopeFixedTokens({k: (v or "").splitlines() for k, v in fixed.items()})
            - estimate_tokens("问题"),
        )
        bound = (
            orch._envelopeFixedTokens({k: (v or "").splitlines() for k, v in fixed.items()})
            + quota
            + estimate_tokens("[历史回忆] 用户: " * 4)
        )
        assert estimate_tokens(envelope) <= bound, (
            f"信封 {estimate_tokens(envelope)} 超出自己那份额度上界 {bound}（未被 compress_envelope 管辖）"
        )


class TestEnvelopeBlockContract:
    """前置条件 3：新增块与淘汰顺位在 `envelope.py` 单源声明。"""

    def test_newBlocksAreDeclaredInBlockOrder(self):
        from neurova.context.envelope import BLOCK_ORDER

        assert "history" in BLOCK_ORDER and "tooling" in BLOCK_ORDER
        assert BLOCK_ORDER.index("history") > BLOCK_ORDER.index("emotion")

    def test_historyIsDroppedRightAfterEmotion(self):
        assert COMPRESS_DROP_ORDER.index("history") == COMPRESS_DROP_ORDER.index("emotion") + 1

    def test_largeEnvelopeDropsHistoryBeforeMemories(self):
        env = build_envelope(
            {
                "memories": "- 记忆甲",
                "history": "- [历史回忆] 用户: " + "很长" * 400,
                "emotion": "😊 joy: 80%",
            }
        )
        from neurova.context.envelope import compress_envelope

        tight = compress_envelope(env, budget_tokens=200, count_tokens=len)
        blocks = parse_envelope(tight)
        assert "history" not in blocks, "<history> 是原文、池内可再召回，应先于 memories 被弃"
        assert "memories" in blocks, "memories 仍是最有价值的兜底块"
