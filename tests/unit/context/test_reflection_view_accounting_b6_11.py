# -*- coding: utf-8 -*-
"""B6-11：反思效力记账改「进视图才记账」+ 未进视图降档兜底（Issue #90 · 决策 D5）。

## 根因（不是"少传一个参数"）

`mark_injected_logs` 在**选中那一刻**就被调用（与 `select_reflection_logs` 同一段），
于是"账目"与"视图"之间没有任何因果：

- 反思条目归档进池的优先级是 60（低于记忆 70、经验等），能否进视图要过
  `SemanticPool.draw` 的相关性门槛；
- 实测（真 `build_context`，无关输入 "今天天气怎么样"）：
  `status=applied`、`trace=['8ab03764-…']`，而**视图里一行 `[反思]` 都没有**。

后果是二重的：① `applied` 这件事被谎报（工单 §10.3 D5："未进视图的反思不再计入
applied"）；② 效力裁决的输入（`injected_reflections` 落进 assistant metadata →
`/chat/feedback` 的 like→validated / dislike→降置信）基于**幻影注入**，用户对一个
从未见过的教训投票（审计 §2.1 P2-9）。

## 本票契约（D5 两条）

1. **进视图才记账**：`applied` 与本轮痕迹只给**真的出现在视图注入面**里的条目。
   "进视图"必须是客观判据，且要覆盖"被 draw 取出、随后被 `compress_envelope`
   整块淘汰"这一形态 —— 故判据取**视图注入面里有没有这条的文本**（`parse_envelope`
   客观解析信封块，用户原文不算注入面）。
2. **降档兜底**：连续 `VIEW_MISS_LIMIT` 轮被选中却从未进视图的条目，走既有降档
   单一事实源 `register_negative_feedback`（只降不删）——否则低相关教训永不生效
   且没有退出路径（审计 §10 D5）。降到 rejected 即脱离恒定注入，池内原文仍在
   （无损归档语义不变）。

## 判据测的是视图，不是分支

最后一条用例走**非池降级分支**（`context_builder is None`）：那里反思确实以独立
消息进了视图，判据必须同样成立 —— 判定规则只有一条（"视图注入面里有没有这条文本"），
不按分支各写一份。
"""

from __future__ import annotations

import asyncio
import os

from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionLogStatus,
    ReflectionType,
)
from neurova.core.turn_context import get_turn_injected_reflections

LESSON = "固件升级前必须先备份配置"
TITLE = "固件升级"


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _growthLog(tmp_path, agentId: str = "a-b611") -> GrowthLogManager:
    manager = MemoryManager(
        db_path=str(tmp_path / "eff.db"), agent_id=agentId, user_id="u1"
    )
    return GrowthLogManager(memory_manager=manager)


def _agent(glog, tmp_path):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.show_empathy = True
    agent.config.agent_id = "a-b611"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = glog
    agent.user_id = "u1"
    agent.agent_id = "a-b611"
    return agent


def _orchestrator(glog, *, use_pool: bool = True, agent=None):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        agent if agent is not None else _agent(glog, None),
        use_pool=use_pool,
        auto_tag=False,
        session_id="sess-b611",
    )
    return orch


async def _lesson(glog, *, lesson: str = LESSON, title: str = TITLE, confidence: float = 0.6):
    return await glog.generate_log(
        type=ReflectionType.ERROR,
        title=title,
        content="正文",
        insights=[lesson],
        confidence=confidence,
    )


def _history(rounds: int = 3):
    return [{"role": "user", "content": f"第{i}轮闲聊"} for i in range(rounds)]


async def _build(orch, user_input: str):
    msgs = await orch.build_context(
        user_input=user_input, session_context=_history(), relevant_memories=[]
    )
    return msgs, get_turn_injected_reflections()


def _injectionText(msgs, user_input: str = "", history: list | None = None) -> str:
    """本轮视图的注入面文本。

    直接调用**生产那处**判定（`reflection_view.injectionSurface`）——判据侧不再
    自带一份"什么是注入面"的副本：两份实现一旦漂移，就会出现"测试说进了视图、
    生产说不算"的分裂（本片修的红灯正是这个形态的半边，副本当时把用户原话
    也算成注入面）。
    """
    from neurova.context.reflection_view import authoredTexts, injectionSurface

    return injectionSurface(msgs, authoredTexts(user_input, history))


class TestViewEntryDecidesAccounting:
    """D5 判据 1：`applied` 与痕迹只给真进视图的条目。"""

    @pytest.mark.asyncio
    async def test_reflection_absent_from_view_is_not_marked_applied(self, tmp_path):
        """无关输入 → 条目没进视图 → 不得记 applied、不得进本轮痕迹。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)

        msgs, trace = await _build(orch, "今天天气怎么样")

        assert LESSON not in _injectionText(msgs, "今天天气怎么样", _history()), (
            "前置条件：无关输入下该教训本就不该进视图"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING, (
            "条目没进视图却被记为 applied —— 这正是 P2-9 的幻影注入"
        )
        assert not trace, f"没进视图的条目不得进本轮痕迹（权威裁决输入），实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_reflection_present_in_view_is_marked_applied_and_traced(self, tmp_path):
        """进了视图 → 仍然照旧记 applied + 痕迹（语义变更不得把真注入一起丢掉）。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)

        msgs, trace = await _build(orch, f"{LESSON}吗")

        assert LESSON in _injectionText(msgs, f"{LESSON}吗", _history()), (
            "前置条件：相关输入应把该教训召回进视图"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED
        assert trace == [entry.id], f"真进视图的条目必须在痕迹里，实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_drawn_then_envelope_dropped_is_not_marked_applied(self, tmp_path):
        """被 draw 取出、随后被信封压缩整块淘汰 → 仍算没进视图。

        判据取视图注入面而不是 draw 的输出集合：`compress_envelope` 超预算时会把
        `<history>` 整块丢掉（`COMPRESS_DROP_ORDER`），那时条目确实没到模型面前。
        """
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)
        # 额度不由魔法数给定：取**固定部分**（免疫句壳 + `<time>`）的复算值，
        # 与生产同一个推导（`_envelopeFixedTokens`，单源）。硬编码常数会在跨
        # 日历边界时失效 —— `<time>` 块随"临近节日"预测多出一行，常数一旦低于
        # 固定部分，`compress_envelope` 的兜底守卫弃掉的是**整封**，被测形态
        # （history 块整块淘汰）根本没发生，判据会以"前置条件不成立"的形式报假红。
        orch._envelopeBudget = lambda *a, **k: orch._envelopeFixedTokens({})  # noqa: SLF001 - 判据要打在真正落地的那一步

        msgs, trace = await _build(orch, f"{LESSON}吗")

        from neurova.context.envelope import parse_envelope

        blocks = parse_envelope(str(msgs[-1].get("content", "")))
        assert blocks, "前置条件：壳 + `<time>` 装得下 ⇒ 信封在场（整封被弃是另一种形态）"
        assert "history" not in blocks, "前置条件：预算不足时 history 块应被整块淘汰"
        assert LESSON not in _injectionText(msgs, f"{LESSON}吗", _history()), (
            "前置条件：被淘汰的块里的文本不该出现在注入面"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING
        assert not trace


class TestMissFallbackDemotes:
    """D5 判据 2：连续未进视图走既有降档单一事实源（只降不删）。"""

    @pytest.mark.asyncio
    async def test_consecutive_misses_demote_confidence(self, tmp_path):
        from neurova.context.reflection_view import VIEW_MISS_LIMIT

        glog = _growthLog(tmp_path)
        entry = await _lesson(glog, confidence=0.6)
        orch = _orchestrator(glog)

        for _ in range(VIEW_MISS_LIMIT):
            await _build(orch, "今天天气怎么样")

        assert glog._cache[entry.id].confidence < 0.6, (
            f"{VIEW_MISS_LIMIT} 轮未进视图仍未降档 —— 低相关教训没有退出路径"
        )
        assert entry.id in glog._cache, "降档只降不删：原文仍在（无损归档语义）"
        assert orch.get_context_health()["reflection_injection"]["demoted"] >= 1

    @pytest.mark.asyncio
    async def test_entering_view_resets_miss_streak(self, tmp_path):
        from neurova.context.reflection_view import VIEW_MISS_LIMIT

        glog = _growthLog(tmp_path)
        entry = await _lesson(glog, confidence=0.6)
        orch = _orchestrator(glog)

        for _ in range(VIEW_MISS_LIMIT - 1):
            await _build(orch, "今天天气怎么样")
        await _build(orch, f"{LESSON}吗")  # 这一轮真进了视图
        for _ in range(VIEW_MISS_LIMIT - 1):
            await _build(orch, "今天天气怎么样")

        assert glog._cache[entry.id].confidence == pytest.approx(0.6), (
            "进视图的那轮必须把连击清零，否则'偶发命中'与'从不命中'被算成同一件事"
        )


class TestReadout:
    """可观测：选中 / 进视图 / 未进视图 / 降档四个数必须可判读。"""

    @pytest.mark.asyncio
    async def test_readout_reports_selected_entered_and_missed(self, tmp_path):
        glog = _growthLog(tmp_path)
        await _lesson(glog)
        orch = _orchestrator(glog)

        await _build(orch, "今天天气怎么样")
        missed = orch.get_context_health()["reflection_injection"]
        assert missed["selected"] == 1, missed
        assert missed["entered_view"] == 0, missed
        assert missed["missed"] == 1, missed

        await _build(orch, f"{LESSON}吗")
        entered = orch.get_context_health()["reflection_injection"]
        assert entered["selected"] == 1, entered
        assert entered["entered_view"] == 1, entered
        assert entered["missed"] == 0, entered


class TestJudgmentFollowsTheViewNotTheBranch:
    """判定规则只有一条：视图注入面里有没有这条文本（不按分支各写一份）。"""

    @pytest.mark.asyncio
    async def test_degraded_branch_view_entry_is_accounted(self, tmp_path):
        """非池降级分支（`context_builder is None`）里反思以独立消息进了视图 → 照旧记账。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        agent = _agent(glog, tmp_path)
        agent.context_builder = None  # 触发降级装配
        agent.use_pool = False
        orch = _orchestrator(glog, use_pool=False, agent=agent)

        msgs, trace = await _build(orch, "随便问点什么")

        assert LESSON in _injectionText(msgs, "随便问点什么", _history()), (
            "前置条件：降级分支把反思以独立消息注入视图"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED
        assert trace == [entry.id]


class TestSurfaceExcludesUserUtterance:
    """注入面判据的退化形态：信封被整封弃掉时，末条消息只剩用户原话。

    `injectionSurface` 的契约是"模型实际看到的**系统注入**面"——用户原文不属于
    注入面（模块 docstring）。但当 `compress_envelope` 的兜底守卫把整封弃掉
    （`budget_tokens` 连免疫句壳都装不下）时，末条消息退化为**裸 user 输入**，
    旧实现对"无信封消息"按正文全文计入 ⇒ 用户自己说的那句被算成注入面。

    后果与 B6-11 要修的幻影注入同型、方向相反：用户复述了某条教训的内容，
    条目从未进视图，却被判定"进了视图"→ 记 `applied` + 进痕迹 → 用户对一个
    自己随口提到的教训投的票被当成对模型注入效果的裁决。
    """

    @pytest.mark.asyncio
    async def test_bare_user_utterance_is_not_injection_surface(self, tmp_path):
        """信封整封弃掉 + 用户原话含教训文本 → 不得判定为"进了视图"。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)
        # 1 token 的额度：免疫句壳都装不下 ⇒ compress_envelope 返回空串（整封弃）。
        orch._envelopeBudget = lambda *a, **k: 1  # noqa: SLF001

        msgs, trace = await _build(orch, f"{LESSON}吗")

        last = str(msgs[-1].get("content", ""))
        assert last == f"{LESSON}吗", "前置条件：信封被整封弃掉，末条消息应只剩用户原话"
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING, (
            "教训只出现在用户原话里，视图注入面里一行都没有 —— 不得记 applied"
        )
        assert not trace, f"没进视图的条目不得进本轮痕迹，实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_history_utterance_is_not_injection_surface(self, tmp_path):
        """会话历史里用户自己说过这句 → 同样不算"教训进了视图"。

        同一根因的第二个命中点：注入面原来把"无信封消息的正文"整条计入，
        于是**用户说过的任何一句**都可能把一条从未注入的教训判成已注入。
        """
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)
        history = [
            {"role": "user", "content": LESSON},
            {"role": "assistant", "content": "好的"},
        ]

        msgs = await orch.build_context(
            user_input="今天天气怎么样", session_context=history, relevant_memories=[]
        )
        trace = get_turn_injected_reflections()

        assert LESSON in "\n".join(str(m.get("content", "")) for m in msgs), (
            "前置条件：这句文本确实在视图里（历史对话窗口），但它是用户说的、不是注入的"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING, (
            "用户历史里说过这句，不等于这条教训被注入过 —— 不得记 applied"
        )
        assert not trace, f"没进视图的条目不得进本轮痕迹，实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_injected_reflection_message_is_still_accounted(self, tmp_path):
        """反向控制：把同一条文本**真注入**成独立消息 → 判定必须翻转。

        上一条的结论不是"这段文本一律不算"：判定跟的是**作者身份**，不是文本内容。
        降级分支（`context_builder is None`）里反思由注入器渲染，落成独立 user
        消息、与任何对话原文都不逐字相同 —— 那时它必须算进注入面。
        """
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        agent = _agent(glog, tmp_path)
        agent.context_builder = None
        orch = _orchestrator(glog, use_pool=False, agent=agent)

        msgs, trace = await _build(orch, "随便问点什么")

        authored = {"随便问点什么", "第0轮闲聊", "第1轮闲聊", "第2轮闲聊"}
        carriers = [
            str(m.get("content", ""))
            for m in msgs
            if LESSON in str(m.get("content", ""))
        ]
        assert carriers, "前置条件：降级分支把反思渲染进视图"
        assert all(text not in authored for text in carriers), (
            "前置条件：承载反思的消息由注入器渲染，与任何对话原文都不逐字相同 —— "
            f"实得 {carriers!r}"
        )
        assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED, (
            "真注入的条目必须照旧记账 —— 判定跟作者身份，不是把这段文本一律排除"
        )
        assert trace == [entry.id], f"真进视图的条目必须在痕迹里，实得 {trace!r}"
