"""post_chat 传动轴修复回归测试（经验结晶闭环审计 2026-09-04 修复 ②④⑥）

断点②：_step_pattern_mining 用 `SkillRegistry()` 新建一次性对象注册 skill_packer
产物——注册即丢弃，运行时 LLM 永远看不到封装技能。修复：换 agent._skill_registry。

断点④：tool_weights 融合（tool_weights.py 并入 closed_loop.AdaptiveToolWeights）后，
post_chat 两处 hasattr 指向不存在的 get_tool_entry/record_failure——生命周期衰减
反哺与遗传高适应度反哺静默 no-op。修复：改用融合版公开 API get_weight/update_weight。

断点⑥：agent_core._on_skill_post_execute 的 record_reuse 在 success 判定之前调用，
失败执行也累加 reuse_count 推高 fitness（正反馈信号污染）。修复：移到 success 之后。
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
from neurova.post_chat_pipeline import PostChatPipeline


def _make_pipeline(agent=None):
    return PostChatPipeline(agent if agent is not None else MagicMock())


class TestPatternMiningUsesAgentRegistry:
    """断点②：pattern 封装技能必须注册进 agent 的真实 registry"""

    @pytest.mark.asyncio
    async def test_packer_skills_registered_into_agent_registry(self):
        agent = MagicMock()
        agent.config.agent_id = "default"
        agent._collect_tool_messages.return_value = [
            {"tool_name": "w1", "success": True},
            {"tool_name": "w2", "success": True},
        ]
        agent._skill_registry = MagicMock()
        agent._skill_registry.has_skill.return_value = False

        pipeline = _make_pipeline(agent)

        evolution = MagicMock()
        pattern_miner = MagicMock()
        pattern_miner.to_skill_template_list.return_value = [
            {"tools": ["w1", "w2"], "support": 3, "success_rate": 0.9}
        ]
        pattern_miner.mine.return_value = [MagicMock()]
        evolution.pattern_miner = pattern_miner
        pipeline._evolution = evolution
        packer = MagicMock()
        pipeline._skill_packer = packer

        await pipeline._step_pattern_mining()

        packer.register_to_skill_registry.assert_called_once()
        registry_arg = packer.register_to_skill_registry.call_args.args[0]
        assert registry_arg is agent._skill_registry

    @pytest.mark.asyncio
    async def test_no_agent_registry_still_persists_service_only(self):
        """registry 不可用时降级：仅写 SkillService，不 new 一次性 registry"""
        agent = MagicMock()
        agent.config.agent_id = "default"
        agent._collect_tool_messages.return_value = [
            {"tool_name": "w1", "success": True},
            {"tool_name": "w2", "success": True},
        ]
        agent._skill_registry = None

        pipeline = _make_pipeline(agent)
        evolution = MagicMock()
        pattern_miner = MagicMock()
        pattern_miner.to_skill_template_list.return_value = [
            {"tools": ["w1", "w2"], "support": 3, "success_rate": 0.9}
        ]
        pattern_miner.mine.return_value = [MagicMock()]
        evolution.pattern_miner = pattern_miner
        pipeline._evolution = evolution
        packer = MagicMock()
        pipeline._skill_packer = packer

        with patch("neurova.skills.skill_service.SkillService") as svc_cls:
            await pipeline._step_pattern_mining()
            svc_cls.assert_called_once()
        packer.register_to_skill_registry.assert_called_once()
        assert packer.register_to_skill_registry.call_args.args[0] is None


class TestWeightsPublicApiFeedback:
    """断点④：生命周期衰减与遗传反哺改走融合版公开 API"""

    def test_adaptive_weights_has_no_dead_methods(self):
        """契约锁定：hasattr 修复的判据方法确实不存在（防回归到旧名）"""
        assert not hasattr(AdaptiveToolWeights, "get_tool_entry")
        assert not hasattr(AdaptiveToolWeights, "record_failure")

    @pytest.mark.asyncio
    async def test_lifecycle_decay_feeds_back_via_get_weight(self):
        """decay 报告里的工具经 update_weight(False) 真实衰减"""
        agent = MagicMock()
        pipeline = _make_pipeline(agent)

        lifecycle = MagicMock()
        lifecycle.evaluate.return_value = {"decay": {"w_dead": 0.5}}
        pipeline._tool_lifecycle = lifecycle

        weights = AdaptiveToolWeights()
        weights.update_weight("w_dead", True)
        mult_before = weights.get_weight("w_dead").adaptive_multiplier

        evolution = MagicMock()
        evolution.tool_weights = weights
        pipeline._evolution = evolution

        await pipeline._step_lifecycle_evaluate()

        w = weights.get_weight("w_dead")
        assert w.failure_count == 1
        assert w.adaptive_multiplier < mult_before

    @pytest.mark.asyncio
    async def test_genetic_fitness_feedback_via_update_weight(self):
        """高适应度基因型的工具获得成功信号"""
        agent = MagicMock()
        pipeline = _make_pipeline(agent)

        # 固定 evolve 返回值，消除交叉随机性；fitness 是计算属性：
        # 0.95×1.0(无时延惩罚)=0.95>0.5 → 应反哺；0.1<0.5 → 不应反哺
        g_hi = ToolGenotype(tool_sequence=["w_hi"], success_rate=0.95)
        g_lo = ToolGenotype(tool_sequence=["w_lo"], success_rate=0.1)
        genetic = MagicMock()
        genetic.evolve.return_value = [g_hi, g_lo]

        weights = AdaptiveToolWeights()
        weights.update_weight("w_hi", True)
        weights.update_weight("w_lo", True)
        hi_before = weights.get_weight("w_hi").adaptive_multiplier
        lo_before = weights.get_weight("w_lo").adaptive_multiplier

        evolution = MagicMock()
        evolution.genetic_engine = genetic
        evolution.tool_weights = weights
        pipeline._evolution = evolution

        # 注册段：fitness<0.8 全被跳过，MagicMock registry 无副作用
        agent._skill_registry = MagicMock()
        await pipeline._step_genetic_evolution()

        hi_after = weights.get_weight("w_hi").adaptive_multiplier
        lo_after = weights.get_weight("w_lo").adaptive_multiplier
        assert hi_after > hi_before, "高适应度工具应获得成功反哺"
        assert lo_after == lo_before, "低适应度工具不应获得反哺"


class TestRecordReuseAfterSuccess:
    """断点⑥：record_reuse 必须在 success 判定之后"""

    def _post_execute(self, success):
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        agent.tool_memory = None
        agent.tool_executor = MagicMock()
        agent._current_user_input = "测试"
        agent.evolution = None

        skill = MagicMock()
        skill.name = "genetic_a_b"
        skill.config = {"tool_sequence": ["a", "b"]}
        result = MagicMock()
        result.success = success
        result.execution_time = 0.1
        result.error = "boom" if not success else ""
        result.metadata = {}
        return agent, skill, result

    def test_failed_skill_does_not_record_reuse(self):
        agent, skill, result = self._post_execute(success=False)
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            orch.genetic_engine = MagicMock()
            agent._on_skill_post_execute(skill, result)
            orch.genetic_engine.record_reuse.assert_not_called()

    def test_successful_skill_still_records_reuse(self):
        agent, skill, result = self._post_execute(success=True)
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            orch.genetic_engine = MagicMock()
            agent._on_skill_post_execute(skill, result)
            orch.genetic_engine.record_reuse.assert_called_once_with(["a", "b"])
