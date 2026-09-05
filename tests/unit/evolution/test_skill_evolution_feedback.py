"""Skill 递归进化三断点修复契约测试（docs/Neurova_OpenClaw工具技能专项对比_2026-09-04.md §7.2）。

断点 #1 传动轴：技能执行 → genetic_engine.record_reuse（reuse_count 递增 → fitness 正反馈）。
断点 #2 持久化：genetic_engine.register_to_skill_registry 接受 skill_service 并写入磁盘 manifest。
断点 #3 回写：AutoSkillImprover.apply_improvement 把已采信的改进写到 skill 本体（config 追加+版本递增+applied 标记），
              post_chat_pipeline 的提案扫描改走 apply_improvement（不再只写反思日志）。
"""

import unittest
from unittest.mock import MagicMock, patch

from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
from neurova.evolution.skill_improver import (
    FailureAnalysis,
    FailurePattern,
    ImprovementType,
    SkillImprovement,
    get_skill_improver,
    reset_skill_improver,
)


def _make_skill(id="genetic_a_b", name="genetic_a_b", sequence=None):
    from neurova.skills.models import Skill, SkillSource

    return Skill(
        id=id,
        name=name,
        version="1.0.0",
        description="genetic skill",
        author="genetic_engine",
        source=SkillSource.LOCAL,
        enabled=True,
        config={
            "tool_sequence": sequence or ["a", "b"],
            "fitness": 0.9,
            "success_rate": 0.9,
        },
    )


class _FakeRegistry:
    """最小 SkillRegistry 契约（register_skill/has_skill/get_skill）。"""

    def __init__(self):
        self.skills = {}

    def register_skill(self, skill, path=None):
        self.skills[skill.name] = skill
        return True

    def has_skill(self, name):
        return name in self.skills

    def get_skill(self, name):
        return self.skills.get(name)

    def list_skills(self):
        return list(self.skills.values())


class _FakeSkillService:
    """记录 register_auto_skill 调用，模拟磁盘持久化。"""

    def __init__(self):
        self.persisted = {}

    def register_auto_skill(self, skill_id, name, description="", version="1.0.0", config=None):
        self.persisted[skill_id] = {"config": config or {}}
        return True


class TestBreakpoint1ReuseFeedback(unittest.TestCase):
    """断点 #1：技能执行反馈 → record_reuse → fitness 提升。"""

    def test_record_reuse_increments_fitness(self):
        engine = ToolGeneticEngine()
        g = ToolGenotype(tool_sequence=["a", "b"], success_rate=0.85)
        engine.add_to_population(g)
        f_before = g.fitness

        self.assertTrue(engine.record_reuse(["a", "b"]))
        self.assertGreater(g.reuse_count, 0)
        self.assertGreater(g.fitness, f_before)

    def test_record_reuse_miss_returns_false(self):
        engine = ToolGeneticEngine()
        self.assertFalse(engine.record_reuse(["x", "y"]))

    def test_agent_post_execute_calls_record_reuse(self):
        """POST_EXECUTE 处理器把 skill.config.tool_sequence 喂给 record_reuse。"""
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        agent.tool_memory = None
        agent.tool_executor = MagicMock()
        agent._current_user_input = "测试"
        agent.evolution = None

        skill = _make_skill(sequence=["a", "b"])
        result = MagicMock()
        result.success = True
        result.execution_time = 0.1
        result.error = ""
        result.metadata = {"skill_kwargs": {}}

        # evolution=None 走 fallback：从 closed_loop 单例拿 genetic_engine
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            orch.genetic_engine = MagicMock()
            agent._on_skill_post_execute(skill, result)
            orch.genetic_engine.record_reuse.assert_called_once_with(["a", "b"])

    def test_post_execute_no_tool_sequence_is_noop(self):
        """无 tool_sequence 的技能（非 genetic 产物）不误触 record_reuse。"""
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        agent.tool_memory = None
        agent.tool_executor = MagicMock()
        agent._current_user_input = "测试"
        agent.evolution = None

        skill = _make_skill(sequence=None)
        skill.config.pop("tool_sequence")
        result = MagicMock()
        result.success = True
        result.execution_time = 0.1
        result.error = ""
        result.metadata = {"skill_kwargs": {}}

        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            orch.genetic_engine = MagicMock()
            agent._on_skill_post_execute(skill, result)
            orch.genetic_engine.record_reuse.assert_not_called()


class TestBreakpoint2GeneticPersistence(unittest.TestCase):
    """断点 #2：genetic 注册支持 skill_service 持久化。"""

    def test_register_without_service_unchanged(self):
        engine = ToolGeneticEngine(validation_threshold=0.8)
        engine.add_to_population(ToolGenotype(tool_sequence=["a", "b"], success_rate=0.9))
        registry = _FakeRegistry()
        n = engine.register_to_skill_registry(registry)
        self.assertEqual(n, 1)
        self.assertEqual(len(registry.skills), 1)

    def test_register_with_service_persists(self):
        engine = ToolGeneticEngine(validation_threshold=0.8)
        engine.add_to_population(ToolGenotype(tool_sequence=["a", "b"], success_rate=0.9))
        registry = _FakeRegistry()
        service = _FakeSkillService()
        engine.register_to_skill_registry(registry, skill_service=service)
        self.assertEqual(len(service.persisted), 1)
        (entry,) = service.persisted.values()
        self.assertEqual(entry["config"]["tool_sequence"], ["a", "b"])

    def test_registry_only_new_skills_persisted(self):
        """已注册过的技能（has_skill 命中）不再重复持久化。"""
        engine = ToolGeneticEngine(validation_threshold=0.8)
        engine.add_to_population(ToolGenotype(tool_sequence=["a", "b"], success_rate=0.9))
        registry = _FakeRegistry()
        registry.skills["genetic_a_b"] = _make_skill()
        service = _FakeSkillService()
        engine.register_to_skill_registry(registry, skill_service=service)
        self.assertEqual(len(service.persisted), 0)


class TestBreakpoint3ApplyImprovement(unittest.TestCase):
    """断点 #3：改进提案应用回 skill 本体。"""

    def setUp(self):
        reset_skill_improver()

    def tearDown(self):
        reset_skill_improver()

    def _improvement(self, skill_id="genetic_a_b"):
        return SkillImprovement(
            improvement_id="imp_test_1",
            skill_id=skill_id,
            improvement_type=ImprovementType.PERFORMANCE,
            description="针对 timeout 模式的改进",
            changes={"suggested_fix": "延长超时并添加重试"},
            reason="检测到 3 次 timeout 错误",
            expected_impact=0.3,
        )

    def test_apply_updates_skill_config(self):
        improver = get_skill_improver()
        registry = _FakeRegistry()
        registry.skills["genetic_a_b"] = _make_skill()

        applied = improver.apply_improvement(self._improvement(), registry)
        self.assertTrue(applied)
        skill = registry.skills["genetic_a_b"]
        self.assertEqual(len(skill.config.get("improvements", [])), 1)
        rec = skill.config["improvements"][0]
        self.assertEqual(rec["type"], "performance")
        self.assertEqual(rec["changes"], {"suggested_fix": "延长超时并添加重试"})
        self.assertIn("applied_at", rec)
        self.assertNotEqual(skill.version, "1.0.0")

    def test_apply_marks_proposal_consumed(self):
        """提案应用后标记 applied 并从 pending 中消失（不重复应用）。"""
        improver = get_skill_improver()
        registry = _FakeRegistry()
        registry.skills["genetic_a_b"] = _make_skill()
        improvement = self._improvement()
        improver._improvements.setdefault("genetic_a_b", []).append(improvement)

        self.assertTrue(improver.apply_improvement(improvement, registry))
        self.assertTrue(improvement.applied)
        self.assertIsNotNone(improvement.applied_at)
        pending = [
            i for i in improver._improvements.get("genetic_a_b", []) if not i.applied
        ]
        self.assertEqual(len(pending), 0)

    def test_apply_missing_skill_returns_false(self):
        improver = get_skill_improver()
        registry = _FakeRegistry()
        self.assertFalse(improver.apply_improvement(self._improvement(), registry))


if __name__ == "__main__":
    unittest.main()

class TestC11WiringSurvival(unittest.TestCase):
    """第三遍审计（覆盖事故回归）：并行重写 _on_skill_post_execute 曾把
    C11 record_skill_usage 调用覆盖丢失——本契约锁定该传动轴存活。"""

    def test_post_execute_records_usage_to_skill_service(self):
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        agent.tool_memory = None
        agent.tool_executor = MagicMock()
        agent._current_user_input = "测试"
        agent.evolution = None

        skill = MagicMock()
        skill.skill_id = "genetic_a_b"
        skill.id = "genetic_a_b"
        skill.name = "genetic_a_b"
        skill.config = {"tool_sequence": ["a", "b"]}
        result = MagicMock()
        result.success = True
        result.execution_time = 0.1
        result.error = ""
        result.metadata = {"skill_kwargs": {}}

        with patch("neurova.skills.skill_service.SkillService") as svc_cls:
            svc = svc_cls.return_value
            with patch("neurova.evolution.closed_loop.get_evolution_orchestrator"):
                agent._on_skill_post_execute(skill, result)
            svc.record_skill_usage.assert_called_once_with("genetic_a_b", success=True)
