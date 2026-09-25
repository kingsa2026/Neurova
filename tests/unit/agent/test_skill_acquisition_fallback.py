"""
红灯测试：查询到所需技能结构但市场缺失时，应回退到自主创建（NL 工具合成）

复现 bug：
    开启主动技能获取(auto_acquire=True)时，`_check_skill_acquisition` 通过
    analyze_task 查询到 "需要哪些技能结构" (skills_needed)，但市场中不存在对应技能
    （acquired 为空），此时仅记录日志 `需要技能: ...但未在市场中找到` 就结束，从不回退到
    自主创建。而真正的创建入口 `_check_nl_synthesis` 又被 `skill_manager.auto_acquire`
    互斥屏蔽 (chat_pipeline.py:532)。

==> 即使查询到了所需结构，agent 也无法自主创建任何工具/技能（死锁）。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent 实例"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "test-agent"
    agent.config.llm_config = MagicMock()
    agent.config.llm_config.model = "test-model"
    agent.config.name = "TestAgent"

    agent.memory_agent = MagicMock()
    agent.context_orchestrator = MagicMock()
    agent.tool_executor = MagicMock()

    agent.skill_manager = None
    agent.tool_synthesizer = None
    agent._skill_registry = MagicMock()
    agent.unified_retriever = None
    agent.crystallizer = None
    agent.trace_manager = None
    agent.neuHebb_manager = None

    return agent


@pytest.fixture
def pipeline(mock_agent):
    return ChatPipeline(mock_agent)


@pytest.fixture
def ctx():
    return ChatContext(user_input="帮我搜索最新新闻")


class TestSkillAcquisitionFallback:
    """查询到所需技能结构、但市场缺失时，应回退到自主创建（NL 合成）"""

    @pytest.mark.asyncio
    async def test_market_miss_triggers_nl_synthesis_fallback(
        self, pipeline, ctx, mock_agent
    ):
        """analyze_task 返回所需技能且 auto_acquire=True，但市场不存在该技能时，
        应回退调用 _check_nl_synthesis 进行自主创建。"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = True
        mock_agent.skill_manager.analyze_task = AsyncMock(
            return_value={
                "skills_needed": [
                    {"skill_name": "web_search_v2", "success": False,
                     "reason": "not in market"},
                ],
                "auto_acquire": True,
            }
        )

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        # 市场获取失败不应仅记录日志而放弃，必须回退到自主创建
        mock_nl.assert_awaited_once()
        assert mock_nl.await_args is not None

    @pytest.mark.asyncio
    async def test_market_miss_passes_force_flag(
        self, pipeline, ctx, mock_agent
    ):
        """回退调用 _check_nl_synthesis 时应传 force=True，从而不被 auto_acquire 互斥屏蔽。"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = True
        mock_agent.skill_manager.analyze_task = AsyncMock(
            return_value={
                "skills_needed": [
                    {"skill_name": "data_clean_v3", "success": False},
                ],
                "auto_acquire": True,
            }
        )

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        mock_nl.assert_awaited_once()
        assert mock_nl.await_args.kwargs.get("force") is True

    @pytest.mark.asyncio
    async def test_no_skills_needed_no_fallback(
        self, pipeline, ctx, mock_agent
    ):
        """analyze_task 返回空 skills_needed 时，不应触发自主创建。"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = True
        mock_agent.skill_manager.analyze_task = AsyncMock(
            return_value={"skills_needed": [], "auto_acquire": False}
        )

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        mock_nl.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_market_hit_no_fallback(
        self, pipeline, ctx, mock_agent
    ):
        """市场中已成功获取技能时，不应重复触发自主创建。"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = True
        mock_agent.skill_manager.analyze_task = AsyncMock(
            return_value={
                "skills_needed": [
                    {"skill_name": "web_search_v2", "success": True},
                ],
                "auto_acquire": True,
            }
        )

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        mock_nl.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_auto_acquire_no_fallback(
        self, pipeline, ctx, mock_agent
    ):
        """未开启主动技能获取时，_check_skill_acquisition 直接返回，不触发创建。"""
        mock_agent.skill_manager = MagicMock()
        mock_agent.skill_manager.auto_acquire = False
        mock_agent.skill_manager.analyze_task = AsyncMock(
            return_value={"skills_needed": [{"skill_name": "x", "success": False}]}
        )

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        mock_nl.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_skill_manager_no_fallback(
        self, pipeline, ctx, mock_agent
    ):
        """无 skill_manager 时直接返回，不触发创建。"""
        mock_agent.skill_manager = None

        with patch.object(pipeline, "_check_nl_synthesis", new=AsyncMock()) as mock_nl:
            await pipeline._check_skill_acquisition(ctx)

        mock_nl.assert_not_awaited()


class TestMarketMissReachesRealEntry:
    """**不走 mock**：市场未命中必须真能走到合成入口。

    上面六条用例都把 `_check_nl_synthesis` 换成 `AsyncMock`，于是只证明了
    "回退调用发出去了"，没证明"调用进去还有事发生"。T-03 把入口判据从
    **用户措辞关键词**改成**能力缺口**后，这条回退就成了死路：市场未命中
    只记一条日志，没人投缺口信号，入口 `detectCapabilityGap()` 读到空即 return
    —— agent 查到了缺什么、市场也确实没有，却依然什么都不会造
    （`force=True` 只绕开 auto_acquire 互斥，绕不开缺口判据）。

    根因在上游：`_check_skill_acquisition` 的「市场未命中」分支才是**真正知道**
    "这条能力取不到"的生产点，缺口信号应当由它在原地投递，而不是让入口去猜。
    判据：把该分支的投递摘掉 ⇒ 本用例必红。
    """

    @staticmethod
    def _agent():
        from neurova.skill_system import SkillRegistry

        agent = SimpleNamespace(
            config=SimpleNamespace(agent_id="agent-market-miss"),
            skill_manager=SimpleNamespace(auto_acquire=True),
            tool_synthesizer=SimpleNamespace(calls=[]),
            _skill_registry=SkillRegistry(),
            tab_name="",
            _tool_messages_list=[],
        )
        agent.tool_synthesizer.synthesize = lambda **kwargs: (
            agent.tool_synthesizer.calls.append(kwargs)
            or SimpleNamespace(success=False, synthesized_tool=None)
        )
        return agent

    @pytest.mark.asyncio
    async def test_market_miss_reallyCallsSynthesizer(self):
        from neurova.agent.capability_gap import clearCapabilityGap
        from neurova.agent.chat_pipeline import ChatPipeline

        clearCapabilityGap("market-miss")
        agent = self._agent()

        async def _analyze_task(user_input):
            return {
                "skills_needed": [
                    {"skill_name": "sqlite_inspect_v1", "success": False,
                     "reason": "not in market"},
                ],
                "auto_acquire": True,
            }

        agent.skill_manager.analyze_task = _analyze_task
        pipeline = ChatPipeline(agent)
        ctx = ChatContext(user_input="帮我看看这个库", session_id="market-miss")

        await pipeline._check_skill_acquisition(ctx)

        assert agent.tool_synthesizer.calls, (
            "市场未命中却根本没走到合成入口——回退是死路（T-03 后入口改为缺口驱动）"
        )

    @pytest.mark.asyncio
    async def test_marketHit_doesNotGoToSynthesizer(self):
        """反向不扩面：市场命中时不得投缺口、不得触发合成。"""
        from neurova.agent.capability_gap import clearCapabilityGap
        from neurova.agent.chat_pipeline import ChatPipeline

        clearCapabilityGap("market-hit")
        agent = self._agent()

        async def _hit(user_input):
            return {
                "skills_needed": [{"skill_name": "sqlite_inspect_v1", "success": True}],
                "auto_acquire": True,
            }

        agent.skill_manager.analyze_task = _hit
        pipeline = ChatPipeline(agent)
        ctx = ChatContext(user_input="帮我看看这个库", session_id="market-hit")

        await pipeline._check_skill_acquisition(ctx)

        assert not agent.tool_synthesizer.calls, "市场已命中却仍触发自主合成"
