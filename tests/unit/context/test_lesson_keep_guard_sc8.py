# -*- coding: utf-8 -*-
"""SC-8 活跃教训引用保护（compression doctrine KEEP 面 + 折叠豁免）。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md §9.4 SC-8）：
1. compression_doctrine 的 KEEP 面增加一条：活跃 lesson（未过期、
   PENDING/VALIDATED 活跃态）引用的原文消息折叠时豁免或降档处理；
2. 教义文本随摘要器 prompt 生效（renderDoctrine 内嵌 _DEFAULT_PROMPT_TEMPLATE）；
3. 机械豁免面（增长门主动折叠路径）：被活跃教训引用的原文消息从折叠区
   豁免、保留在视图（教训正在指导当前行为时，证据原文不得与教训脱节）；
4. 过期 lesson 不豁免（同场景对照）；
5. 引用判定取**结构匹配**（tool 行 name / assistant.tool_calls 的 function.name
   = 教训 subject），不做正文子串臆测；
6. 严格变小守卫照常；容量优先（硬水位路径不做机械豁免，由 KEEP 教义指导摘要保留）。
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens


def _mk_agent(model: str = "test-model"):
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.llm_model = model
    mock_agent.config.agent_id = "a-sc8-iso"
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-sc8-iso"
    mock_agent.agent_id = "a-sc8-iso"
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _summary_rows(view):
    return [m for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))]


def _hasMsg(view, tag: str) -> bool:
    return any(tag in str(m.get("content", "")) for m in view)


def _scenarioWithPair(orch: ContextOrchestrator, key: str, pairAt: int = 20, tail: int = 8):
    """增长门场景：pairAt 处放一对 search 工具调用/结果（被教训引用的原文）。"""
    msgs = [_long_msg(i) for i in range(pairAt)]
    msgs.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_sc8", "function": {"name": "search", "arguments": "{}"}}],
        }
    )
    msgs.append({"role": "tool", "tool_call_id": "call_sc8", "name": "search", "content": "工具结果原文"})
    msgs += [_long_msg(i + 100) for i in range(tail)]
    total = estimate_window_tokens(msgs)
    budget = orch._effectiveWindowBudget(int(total * 1.25))
    assert total <= budget
    cache = orch._window_cache_slot(key)
    cache["last_fold_tokens"] = int(total * 0.5)
    cache["last_fold_msgs"] = 0
    return msgs, budget, total


def _writeLesson(agentId: str, subject: str = "search", *, expired: bool = False):
    from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

    expires = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
    get_meta_ledger().create_record(
        agent_id=agentId,
        kind="lesson",
        type="monitoring",
        content=f"search 的用法教训",
        confidence=0.9,
        metadata={
            "subject": subject,
            "operator": "drift",
            "recommendation": "prefer_other",
            "expires_at": expires.isoformat(),
            "text": f"search 的用法教训",
        },
    )


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import reset_self_model_engine

    reset_meta_ledger()
    reset_self_model_engine()
    yield
    reset_meta_ledger()
    reset_self_model_engine()


def _mk_orchestrator() -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
    orch._window_hard_limit = 10**9
    return orch


class TestDoctrineKeepFace:
    """KEEP 面新增：活跃教训证据原文的保护条款。"""

    def test_keep_rule_contains_active_lesson_clause(self):
        from neurova.context.compression_doctrine import defaultDoctrine, renderDoctrine

        text = renderDoctrine()
        assert "活跃教训" in text, "KEEP 面应有活跃教训保护条款"
        assert "活跃教训" in defaultDoctrine()["keep"]
        assert "证据原文" in defaultDoctrine()["keep"]

    def test_doctrine_version_bumped(self):
        from neurova.context.compression_doctrine import DOCTRINE_VERSION

        assert DOCTRINE_VERSION == "1.1.0", "规则文本变更必须递增版本（对账用）"

    def test_summarizer_prompt_carries_new_clause(self):
        from neurova.context.summarizing_compressor import _DEFAULT_PROMPT_TEMPLATE

        assert "活跃教训" in _DEFAULT_PROMPT_TEMPLATE, "教义经 renderDoctrine 内嵌摘要 prompt"


class TestLessonKeepGuardFold:
    """增长门折叠：活跃教训引用的原文消息豁免（留在视图）。"""

    @pytest.mark.asyncio
    async def test_active_lesson_reference_survives_fold(self):
        from neurova.context_pool import assertCompactionShrinks

        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _scenarioWithPair(orch, "sc8-session")
        _writeLesson(orch._agent.config.agent_id, "search")

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc8-session")

        assert _summary_rows(view), "豁免是软保护：折叠仍应发生"
        assert _hasMsg(view, "工具结果原文"), "被活跃教训引用的结果原文不得被折（豁免）"
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in view
        ), "被引用的调用行不得被折"
        assert not _hasMsg(view, "长消息0"), "未被引用的老增量照常折叠"
        assertCompactionShrinks(total, estimate_window_tokens(view))
        slot = orch._context_health["fold_suppression"]
        assert slot["lesson_protected_last"] >= 2, "豁免条数要进读数面"

    @pytest.mark.asyncio
    async def test_expired_lesson_does_not_protect(self):
        """过期 lesson 不豁免：同场景照常折叠。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _scenarioWithPair(orch, "sc8-session")
        _writeLesson(orch._agent.config.agent_id, "search", expired=True)

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc8-session")

        assert _summary_rows(view)
        assert not _hasMsg(view, "工具结果原文"), "过期教训不豁免：引用原文照常折叠"

    @pytest.mark.asyncio
    async def test_unrelated_lesson_does_not_block_fold(self):
        """subject 不在窗内的活跃教训：不豁免任何消息，折叠照常。"""
        orch = _mk_orchestrator()

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, total = _scenarioWithPair(orch, "sc8-session")
        _writeLesson(orch._agent.config.agent_id, "not_in_window_tool")

        view = await orch._apply_window_budget(msgs, budget, cache_key="sc8-session")

        assert _summary_rows(view)
        assert not _hasMsg(view, "长消息0"), "无命中不改变折叠行为"

    @pytest.mark.asyncio
    async def test_plain_text_mention_is_not_a_reference(self):
        """引用判定是结构匹配：正文提到工具名不算被引用（不豁免）。"""
        from neurova.context.fold_trigger import lessonProtectedStart

        msgs = [
            {"role": "user", "content": "请帮我 search 一下"},
            {"role": "tool", "tool_call_id": "c1", "name": "search", "content": "r"},
        ]
        lessons = [{"subject": "search", "expires_at": ""}]
        assert lessonProtectedStart(msgs, lessons) == 1, "正文提及不豁免，tool 行才豁免"


class TestLessonGuardPure:
    """纯判据：lessonIsActive / lessonProtectedStart。"""

    def test_active_predicate(self):
        from neurova.context.fold_trigger import lessonIsActive

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        past = (datetime.now(timezone.utc) + timedelta(hours=-1)).isoformat()
        assert lessonIsActive({"subject": "t"}) is True, "无过期时间 = 活跃"
        assert lessonIsActive({"subject": "t", "expires_at": future}) is True
        assert lessonIsActive({"subject": "t", "expires_at": past}) is False, "过期不活跃"
        assert lessonIsActive({"subject": "t", "status": "pending"}) is True
        assert lessonIsActive({"subject": "t", "status": "validated"}) is True
        assert lessonIsActive({"subject": "t", "status": "expired"}) is False, "失效态不活跃"

    def test_protected_start_finds_earliest_reference(self):
        from neurova.context.fold_trigger import lessonProtectedStart

        msgs = [
            {"role": "user", "content": "a"},
            {"role": "tool", "tool_call_id": "c1", "name": "search", "content": "r1"},
            {"role": "user", "content": "b"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "function": {"name": "search", "arguments": "{}"}}],
            },
        ]
        lessons = [{"subject": "search", "expires_at": ""}]
        assert lessonProtectedStart(msgs, lessons) == 1, "最早被引用消息的下标"
        assert lessonProtectedStart(msgs, []) == len(msgs), "无教训不保护"
        assert lessonProtectedStart([], lessons) == 0

    def test_expired_lesson_never_protects(self):
        from neurova.context.fold_trigger import lessonProtectedStart

        past = (datetime.now(timezone.utc) + timedelta(hours=-1)).isoformat()
        msgs = [{"role": "tool", "tool_call_id": "c1", "name": "search", "content": "r1"}]
        assert lessonProtectedStart(msgs, [{"subject": "search", "expires_at": past}]) == 1
