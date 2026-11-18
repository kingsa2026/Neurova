"""E5 件 1：池分支（use_pool=True）补元认知教训（lessons）注入。

红线（四域修复方案 E5 卡）：meta lessons 注入此前只走非池分支
（orchestrator.build_context 非池路径 → builder → injector._build_metacog_lessons），
默认池分支（use_pool=True，生产主链路）不注 lessons——反思教训只进台账、不改行为。

判据：
- 池分支会话的上下文信封（末条 user 消息 <system-reminder>）含活跃 lesson 文本；
- 过期 lesson 不出现；
- 预算仍 ≤3 条（复用 injector._build_metacog_lessons 单一选取逻辑，不新造第二套）；
- 注入器无归属身份时零注入（与非池分支同口径）。
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger
from neurova.context.envelope import parse_envelope
from neurova.context.orchestrator import ContextOrchestrator

AGENT = "e5_pool_lessons_agent"


def _seedLesson(text: str, operator: str = "avoid_tool", expires_at: str = None) -> str:
    """直接经台账 create_record 播种一条 lesson（kind='lesson'）。"""
    metadata = {"operator": operator, "text": text}
    if expires_at:
        metadata["expires_at"] = expires_at
    return get_meta_ledger(AGENT).create_record(
        agent_id=AGENT,
        kind="lesson",
        type="insight",
        content=text,
        confidence=0.9,
        metadata=metadata,
    )


def _makeOrchestrator() -> ContextOrchestrator:
    mock_agent = MagicMock()
    mock_agent.config.name = "e5_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.agent_id = AGENT
    mock_agent.soul = "测试灵魂"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.memory_manager = MagicMock()

    orchestrator = ContextOrchestrator(mock_agent, use_pool=True)
    # 与 Agent.init_context_system 同一装配形态：真注入器 + 教训归属身份
    from neurova.context.injector import UnifiedContextInjector
    from neurova.context.models import TokenBudget

    orchestrator._unifiedInjector = UnifiedContextInjector(
        memory_manager=None,
        token_budget=TokenBudget(max_total=16000),
        metacog_agent_id=AGENT,
    )
    return orchestrator


def _lastEnvelope(context: list) -> dict:
    assert context and context[-1]["role"] == "user"
    return parse_envelope(context[-1].get("content", ""))


class TestPoolLessonsInjection:
    @pytest.mark.asyncio
    async def test_poolEnvelopeCarriesActiveLesson(self):
        """池分支会话信封含活跃 lesson 文本（改前恒缺——生产主链路吃不到）。"""
        orchestrator = _makeOrchestrator()
        _seedLesson("避免用 bad_tool 做站内抓取，改用 web_fetch")
        with patch.object(orchestrator, "get_tools_description", new_callable=AsyncMock) as tools:
            tools.return_value = ""
            context = await orchestrator.build_context(
                user_input="帮我抓取数据", session_context=[]
            )
        blocks = _lastEnvelope(context)
        assert "lessons" in blocks, f"池分支信封必须含 lessons 块，实际块：{sorted(blocks)}"
        assert "避免用 bad_tool 做站内抓取" in blocks["lessons"]

    @pytest.mark.asyncio
    async def test_expiredLessonNotInjected(self):
        """过期 lesson 不出现（expires_at 过滤口径与非池分支一致）。"""
        orchestrator = _makeOrchestrator()
        past = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat()
        _seedLesson("已过期的教训文本", expires_at=past)
        _seedLesson("仍然活跃的教训文本")
        with patch.object(orchestrator, "get_tools_description", new_callable=AsyncMock) as tools:
            tools.return_value = ""
            context = await orchestrator.build_context(user_input="你好", session_context=[])
        lessons = _lastEnvelope(context).get("lessons", "")
        assert "仍然活跃的教训文本" in lessons
        assert "已过期的教训文本" not in lessons

    @pytest.mark.asyncio
    async def test_lessonsBudgetCappedAtThree(self):
        """预算仍 ≤3 条（复用 _build_metacog_lessons 既有口径，不扩注入面）。"""
        orchestrator = _makeOrchestrator()
        for i in range(5):
            _seedLesson(f"第{i}条教训文本内容")
        with patch.object(orchestrator, "get_tools_description", new_callable=AsyncMock) as tools:
            tools.return_value = ""
            context = await orchestrator.build_context(user_input="你好", session_context=[])
        blocks = _lastEnvelope(context)
        assert "lessons" in blocks, f"池分支信封必须含 lessons 块，实际块：{sorted(blocks)}"
        lines = [ln for ln in blocks["lessons"].splitlines() if ln.strip()]
        assert len(lines) == 3, f"5 条播种应恰好注满预算 3 条，实际 {len(lines)}：{lines}"

    @pytest.mark.asyncio
    async def test_noIdentityNoInjection(self):
        """注入器无归属身份（_metacog_agent_id 缺省）→ 零注入，不造恒定噪声面。"""
        orchestrator = _makeOrchestrator()
        orchestrator._unifiedInjector._metacog_agent_id = None
        _seedLesson("不应出现的教训")
        with patch.object(orchestrator, "get_tools_description", new_callable=AsyncMock) as tools:
            tools.return_value = ""
            context = await orchestrator.build_context(user_input="你好", session_context=[])
        blocks = _lastEnvelope(context)
        assert "lessons" not in blocks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
