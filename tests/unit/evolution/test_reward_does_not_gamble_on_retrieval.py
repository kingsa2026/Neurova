"""T-06：强化口径——"永不失败"的元检索工具不再被遗传反哺顶到权重上限。

事故（2026-09-24 取证）：`data/evolution/tool_weights.json` 现值里
`memory_search` 被推到 **1.500（上限）**、`voice_memory_search` 1.411，
而唯一真能解题的 `run_code` 是 `success=0, failure=2, adaptive_multiplier=0.8924`
—— **被抬高门槛**。成因：遗传反哺按"基因型适应度 > 0.5"给序列内每个工具记一张
成功票（`post_chat_pipeline._step_genetic_evolution`），而纯检索基因型
（`['memory_search','tool_search']` 之类）**结构上没有失败可能** ⇒ 单调涨到上限，
把能真正解决问题的执行原语挤下去。

同根第二处：市场自动发布对内置元工具也是零信息增量重复
（实测 `auto-tool_search` 被发布两遍）。

判据（教义第 1 条）：撤掉反哺禁令 ⇒ 纯检索基因型重新把 `memory_search`
推到上限（`TestReverseLock` 即此判据）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.genetic_engine import ToolGenotype
from neurova.post_chat_pipeline import PostChatPipeline


def _makePipeline():
    return PostChatPipeline(MagicMock())


def _driverPipeline(genotypes, weights):
    """把反哺链路的输入替身接到**生产方法**上（`_step_genetic_evolution` 本身）。"""
    agent = MagicMock()
    agent.config.agent_id = "default"
    agent._skill_registry = MagicMock()
    agent._collect_tool_messages.return_value = []

    genetic = MagicMock()
    genetic.evolve.return_value = list(genotypes)
    evolution = MagicMock()
    evolution.genetic_engine = genetic
    evolution.pattern_miner = MagicMock()
    evolution.pattern_miner.sequence_count = 1
    evolution.pattern_miner.get_top_patterns.return_value = []
    evolution.tool_weights = weights

    pipeline = PostChatPipeline(agent)
    pipeline._evolution = evolution
    return pipeline


def _retrievalOnly():
    return ToolGenotype(tool_sequence=["memory_search", "recall_history"], success_rate=0.99)


def _withRealExecution():
    return ToolGenotype(tool_sequence=["memory_search", "run_code"], success_rate=0.99)


class TestRetrievalOnlyGenotypeIsNotRewarded:
    @pytest.mark.asyncio
    async def test_retrievalOnlyGenotype_doesNotRaiseWeights(self):
        weights = AdaptiveToolWeights()
        weights.register_tool("memory_search")
        weights.update_weight("memory_search", False)  # 先落一条失败票，便于观察方向
        before = weights.get_weight("memory_search").adaptive_multiplier

        await _driverPipeline([_retrievalOnly()], weights)._step_genetic_evolution()

        after = weights.get_weight("memory_search").adaptive_multiplier
        assert after == before, f"纯检索基因型不应获得成功反哺：{before} → {after}"

    @pytest.mark.asyncio
    async def test_retrievalOnlyGenotype_doesNotReachCeiling(self):
        """重复跑多轮也不得单调涨到上限（事故读数就是 1.500）。"""
        weights = AdaptiveToolWeights()
        weights.register_tool("memory_search")
        for _ in range(12):
            await _driverPipeline([_retrievalOnly()], weights)._step_genetic_evolution()

        value = weights.get_weight("memory_search").adaptive_multiplier
        assert value < weights.max_multiplier, f"元检索仍被顶到上限：{value}"

    @pytest.mark.asyncio
    async def test_mixedGenotype_metaMemberStillNotRewarded(self):
        """混合基因型里的**元检索成员**也不得搭便车（同根剩余形态）。

        真种群实测（40 轮）：只按"整条序列全为元检索"过滤时，
        `['memory_search','file_read']` 这类占多数的混合型照样把 memory_search
        抬到 1.500 上限 —— 修的是同一个根因，一并修净（教义第 5 条）。
        """
        weights = AdaptiveToolWeights()
        weights.register_tool("memory_search")
        weights.register_tool("run_code")
        weights.update_weight("memory_search", False)
        before = weights.get_weight("memory_search").adaptive_multiplier

        await _driverPipeline([_withRealExecution()], weights)._step_genetic_evolution()

        after = weights.get_weight("memory_search").adaptive_multiplier
        assert after == before, f"混合基因型里元检索搭了便车：{before} → {after}"

    @pytest.mark.asyncio
    async def test_mixedGenotypeWithRealExecution_rewards(self):
        """反向不扩面：带真执行原语的基因型仍应受益（不误伤正反馈）。"""
        weights = AdaptiveToolWeights()
        weights.register_tool("memory_search")
        weights.register_tool("run_code")
        before = weights.get_weight("run_code").adaptive_multiplier

        await _driverPipeline([_withRealExecution()], weights)._step_genetic_evolution()

        after = weights.get_weight("run_code").adaptive_multiplier
        assert after > before, f"带真执行的基因型被误伤：{before} → {after}"


class TestBuiltinMetaToolIsNotRepublished:
    @pytest.mark.asyncio
    async def test_builtinMetaTool_notRepublishedToMarket(self):
        marketplace = MagicMock()
        marketplace.add_tool = MagicMock()
        agent = MagicMock()
        agent.config.agent_id = "agent_kai"
        agent._collect_tool_messages.return_value = [
            {"tool_name": "tool_search", "type": "tool_result", "success": True, "result": {}},
            {"tool_name": "memory_search", "type": "tool_result", "success": True, "result": {}},
        ]
        pipeline = PostChatPipeline(agent)
        pipeline.configure(tool_marketplace=marketplace)

        await pipeline._step_marketplace_publish()

        published = [call[0][0].name for call in marketplace.add_tool.call_args_list]
        assert "tool_search" not in published, f"内置元工具被零信息增量发布：{published}"


class TestSingleSourceMetatoolRoster:
    def test_rosterHasOneDefinition(self):
        """名单只有一处定义：`tool_layers/capability_graph`（不新增配置/env）。"""
        from neurova.tool_layers.capability_graph import is_meta_retrieval_tool

        assert is_meta_retrieval_tool("memory_search")
        assert is_meta_retrieval_tool("recall_history")
        assert not is_meta_retrieval_tool("run_code")
        assert not is_meta_retrieval_tool("query_database")

    def test_rosterCoversControlTools(self):
        """控制工具（tool_search/tool_describe/tool_call）也在名单里 —— 同根扫荡。"""
        from neurova.context.tool_search import CONTROL_TOOL_NAMES
        from neurova.tool_layers.capability_graph import is_meta_retrieval_tool

        for name in CONTROL_TOOL_NAMES:
            assert is_meta_retrieval_tool(name), f"控制工具 {name} 不在元检索名单里"

    def test_observationReadback(self):
        """反哺禁令命中数必须有读侧（只写不读是断点，AGENTS §2）。"""
        from neurova.evolution.rsi.orchestrator import _readRewardGuardMetrics
        from neurova.tool_layers.capability_graph import noteMetaRewardSkip

        noteMetaRewardSkip("memory_search")
        readout = _readRewardGuardMetrics()
        assert readout["total"] >= 1, f"反哺禁令没有读侧读数：{readout}"


class TestReverseLock:
    @pytest.mark.asyncio
    async def test_removingGuard_letsRetrievalReachCeiling(self, monkeypatch):
        """反向锁：撤掉反哺禁令 ⇒ `memory_search` 重新单调冲到上限。"""
        from neurova import post_chat_pipeline as _pc

        monkeypatch.setattr(_pc, "_isMetaRetrievalTool", lambda name: False)
        weights = AdaptiveToolWeights()
        weights.register_tool("memory_search")
        pipeline = _driverPipeline([_retrievalOnly()], weights)

        for _ in range(30):
            await pipeline._step_genetic_evolution()

        value = weights.get_weight("memory_search").adaptive_multiplier
        assert value == weights.max_multiplier, f"反向锁不成立：{value} != {weights.max_multiplier}"
