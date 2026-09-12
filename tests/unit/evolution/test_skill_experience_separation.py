"""经验-技能定义分离 + usage_stats 测试（QP 对齐启发 #2）。

两个已知痛点：
1. AutoSkillImprover.apply_improvement 只把改进追加进 config.improvements
   元数据——LLM 永远看不到，行为零变化；
2. 技能级没有自动淘汰机制（只有工具级遗忘曲线），只生不死。

设计（对齐 jiuwenswarm evolutions.json 模型）：
- 进化经验先作为 applied 记录立即生效（组合进技能描述，LLM 下一轮可见），
  技能定义基线保持纯净（config.base_description）；
- usage_stats（times_presented/times_used/positive/negative）按执行成败累积；
- 未合并记录攒够阈值 → 定期重建技能定义（先归档、可回滚）；
- 淘汰依据 = 使用统计（min_uses + 成功率上限）；自动禁用默认关
  （NEUROVA_SKILL_AUTO_RETIRE=1 才生效，默认只上报候选）。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# 机制测试作用域：本文件验证经验库/桥接/持久化机制本身——评审闸的待审流
# 由 test_skill_review_gate.py 覆盖，故此处统一关闭闸（治理后默认开）
_GATE_PATCHER = None


def setUpModule():
    global _GATE_PATCHER
    _GATE_PATCHER = patch.dict(os.environ, {"NEUROVA_SKILL_REVIEW_GATE": "0"})
    _GATE_PATCHER.start()


def tearDownModule():
    if _GATE_PATCHER:
        _GATE_PATCHER.stop()


from neurova.evolution.skill_experience import (
    SkillExperienceStore,
    get_skill_experience_store,
    reset_skill_experience_store,
    run_skill_experience_maintenance,
)
from neurova.evolution.skill_improver import (
    ImprovementType,
    SkillImprovement,
    get_skill_improver,
    reset_skill_improver,
)


class _FakeSkill:
    def __init__(self, name, description="base desc"):
        self.name = name
        self.description = description
        self.version = "1.0.0"
        self.config = {}


class _FakeRegistry:
    def __init__(self):
        self.skills = {}
        self.enabled_changes = []

    def register(self, skill):
        self.skills[skill.name] = skill

    def get_skill(self, skill_name):
        return self.skills.get(skill_name)

    def set_skill_enabled(self, skill_name, enabled):
        self.enabled_changes.append((skill_name, enabled))
        return skill_name in self.skills


class _FakeSkillService:
    def __init__(self):
        self.updates = []
        self.disabled = []

    def update_auto_skill(self, skill_id, version=None, config=None):
        self.updates.append((skill_id, version))
        return True

    def disable_skill(self, skill_id):
        self.disabled.append(skill_id)
        return {"success": True}


class SkillExperienceStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "skill_exp.json"
        self.registry = _FakeRegistry()
        self.service = _FakeSkillService()
        self.skill = _FakeSkill("sk_a")
        self.registry.register(self.skill)

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self, **kwargs):
        return SkillExperienceStore(**kwargs)

    def test_record_experience_immediately_applied_to_description(self):
        """applied 记录立即生效：注册表在场时组合进描述，基线保持纯净。"""
        store = self._store()
        rec = store.record_experience(
            "sk_a", "执行前先检查参数 X", source="improver", registry=self.registry
        )
        self.assertIsNotNone(rec)
        self.assertIn("执行前先检查参数 X", self.skill.description)
        self.assertIn("base desc", self.skill.description)
        # 定义基线不被污染（分离原则：经验在 store，定义可回溯）
        self.assertEqual(self.skill.config["base_description"], "base desc")

    def test_record_experience_dedup_same_content(self):
        store = self._store()
        first = store.record_experience("sk_a", "same guidance", registry=self.registry)
        second = store.record_experience("sk_a", "same guidance", registry=self.registry)
        self.assertIsNotNone(first)
        self.assertIsNone(second)  # 同内容不重复
        self.assertEqual(len(store.get_records("sk_a")), 1)

    def test_record_usage_counters(self):
        store = self._store()
        store.record_usage("sk_a", success=True)
        store.record_usage("sk_a", success=True)
        store.record_usage("sk_a", success=False)
        usage = store.get_usage("sk_a")
        self.assertEqual(usage["times_used"], 3)
        self.assertEqual(usage["positive"], 2)
        self.assertEqual(usage["negative"], 1)

    def test_compose_description_bounded_to_recent_five(self):
        store = self._store()
        for i in range(7):
            store.record_experience("sk_a", f"guidance_{i}")
        composed = store.compose_effective_description("sk_a")
        self.assertIn("guidance_6", composed)
        self.assertIn("guidance_2", composed)
        self.assertNotIn("guidance_1", composed)  # 只保留最近 5 条

    def test_pending_rebuild_counts_unmerged(self):
        store = self._store()
        for i in range(3):
            store.record_experience("sk_a", f"g{i}")
        self.assertEqual(store.pending_rebuild("sk_a"), 3)
        store.record_usage("sk_a", success=True)  # usage 不影响 pending
        self.assertEqual(store.pending_rebuild("sk_a"), 3)

    def test_rebuild_archives_and_merges(self):
        store = self._store(rebuild_threshold=3)
        for i in range(3):
            store.record_experience("sk_a", f"g{i}", registry=self.registry)  # 首条捕获纯净基线
        self.skill.description = "被并行修改过的描述"  # 模拟运行期漂移
        ok = store.rebuild_skill("sk_a", self.registry, skill_service=self.service)
        self.assertTrue(ok)
        # 归档保存了重建前定义（漂移后的现场）
        archives = store.get_archives("sk_a")
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0]["description"], "被并行修改过的描述")
        self.assertEqual(archives[0]["version"], "1.0.0")
        # 重建后：全部 pending 合并、从纯净基线组合（不继承漂移、不双计）、
        # 版本 minor 递增
        self.assertEqual(store.pending_rebuild("sk_a"), 0)
        self.assertIn("base desc", self.skill.description)
        self.assertIn("g0", self.skill.description)
        self.assertIn("g2", self.skill.description)
        self.assertNotIn("被并行修改过的描述", self.skill.description)
        self.assertEqual(self.skill.version, "1.1.0")
        self.assertEqual(self.service.updates, [("sk_a", "1.1.0")])

    def test_rebuild_below_threshold_returns_false(self):
        store = self._store(rebuild_threshold=5)
        store.record_experience("sk_a", "only one")
        self.assertFalse(store.rebuild_skill("sk_a", self.registry, skill_service=self.service))

    def test_rollback_restores_archived_definition(self):
        store = self._store(rebuild_threshold=1)
        store.record_experience("sk_a", "g0", registry=self.registry)
        store.rebuild_skill("sk_a", self.registry, skill_service=self.service)
        self.assertEqual(self.skill.version, "1.1.0")
        ok = store.rollback_skill("sk_a", self.registry, skill_service=self.service)
        self.assertTrue(ok)
        self.assertEqual(self.skill.version, "1.0.0")
        self.assertEqual(self.skill.config["base_description"], "base desc")
        self.assertEqual(self.service.updates[-1], ("sk_a", "1.0.0"))
        # 回滚后经验记录保留在台账（审计），但不再自动重建同内容
        self.assertEqual(len(store.get_records("sk_a")), 1)
        self.assertEqual(store.pending_rebuild("sk_a"), 0)

    def test_retirement_candidates_by_usage_stats(self):
        store = self._store(retire_min_uses=10, retire_max_success_rate=0.3)
        for _ in range(10):
            store.record_usage("sk_bad", success=False)
        store.record_usage("sk_bad", success=True)
        store.record_usage("sk_bad", success=True)  # 2/12 ≈ 0.17 < 0.3
        for _ in range(10):
            store.record_usage("sk_good", success=True)  # 1.0
        for _ in range(3):
            store.record_usage("sk_few", success=False)  # 次数不足

        candidates = store.get_retirement_candidates()
        self.assertIn("sk_bad", candidates)
        self.assertNotIn("sk_good", candidates)
        self.assertNotIn("sk_few", candidates)

    def test_mark_retired_idempotent_and_excluded(self):
        store = self._store(retire_min_uses=1, retire_max_success_rate=0.3)
        store.record_usage("sk_bad", success=False)
        self.assertTrue(store.mark_retired("sk_bad", reason="test"))
        self.assertFalse(store.mark_retired("sk_bad", reason="again"))  # 幂等
        self.assertEqual(store.get_retirement_candidates(), [])


class SkillExperiencePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "skill_exp.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_roundtrip(self):
        store = SkillExperienceStore()
        store.record_experience("sk_a", "guidance one")
        store.record_usage("sk_a", success=True)
        store.record_usage("sk_a", success=False)
        store.mark_retired("sk_dead", reason="low rate")
        store.save(self.path)

        restored = SkillExperienceStore()
        restored.load(self.path)
        self.assertEqual(len(restored.get_records("sk_a")), 1)
        self.assertEqual(restored.get_records("sk_a")[0].content, "guidance one")
        self.assertEqual(restored.get_usage("sk_a")["times_used"], 2)
        self.assertIn("sk_dead", restored._retired)

    def test_unattached_never_writes(self):
        store = SkillExperienceStore()
        store.record_experience("sk_a", "g")
        store.record_usage("sk_a", success=True)
        self.assertFalse(self.path.exists())


class ApplyImprovementWiringTest(unittest.TestCase):
    """apply_improvement 必须写 applied 经验记录（修复"只改元数据不改行为"）。"""

    def setUp(self):
        reset_skill_improver()
        reset_skill_experience_store()
        self.registry = _FakeRegistry()
        self.skill = _FakeSkill("sk_imp")
        self.registry.register(self.skill)

    def tearDown(self):
        reset_skill_improver()
        reset_skill_experience_store()

    def test_apply_improvement_writes_behavior_changing_experience(self):
        improver = get_skill_improver()
        proposal = SkillImprovement(
            improvement_id="imp_1",
            skill_id="sk_imp",
            improvement_type=ImprovementType.ERROR_HANDLING,
            description="针对 invalid_input 模式的改进",
            changes={"suggested_fix": "添加输入验证和预处理"},
            reason="检测到 3 次 invalid_input 错误",
        )
        ok = improver.apply_improvement(proposal, self.registry)
        self.assertTrue(ok)

        store = get_skill_experience_store()
        records = store.get_records("sk_imp")
        self.assertEqual(len(records), 1, "改进必须落为 applied 经验记录")
        self.assertIn("添加输入验证和预处理", records[0].content)
        # 立即生效：描述里可见（LLM 下轮工具面就能看到）
        self.assertIn("添加输入验证和预处理", self.skill.description)


class PostExecuteWiringTest(unittest.TestCase):
    """_on_skill_post_execute 必须同步累积 usage_stats（淘汰依据的数据源）。"""

    def setUp(self):
        reset_skill_experience_store()

    def tearDown(self):
        reset_skill_experience_store()

    def test_post_execute_bumps_usage_stats(self):
        from neurova.agent_core import Agent

        stub = SimpleNamespace(
            tool_memory=None,
            tool_executor=None,
            growth_log_manager=None,
            config=SimpleNamespace(agent_id="skill_agent"),
            _current_user_input="",
        )
        skill = SimpleNamespace(skill_id="sk_wire", name="weather")

        Agent._on_skill_post_execute(
            stub, skill=skill, result=SimpleNamespace(success=True, error="", execution_time=1.0, metadata={})
        )
        Agent._on_skill_post_execute(
            stub, skill=skill, result=SimpleNamespace(success=False, error="boom", execution_time=1.0, metadata={})
        )

        usage = get_skill_experience_store().get_usage("sk_wire")
        self.assertEqual(usage["times_used"], 2)
        self.assertEqual(usage["positive"], 1)
        self.assertEqual(usage["negative"], 1)


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        reset_skill_experience_store()
        self.registry = _FakeRegistry()
        self.service = _FakeSkillService()
        self.store = get_skill_experience_store()

    def tearDown(self):
        reset_skill_experience_store()

    def test_maintenance_rebuilds_due_skills(self):
        self.registry.register(_FakeSkill("sk_due"))
        for i in range(5):
            self.store.record_experience("sk_due", f"g{i}")
        result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_due", result["rebuilt"])
        self.assertIn("g4", self.registry.get_skill("sk_due").description)

    def test_maintenance_retire_off_by_default_only_reports(self):
        self.registry.register(_FakeSkill("sk_bad"))
        for _ in range(12):
            self.store.record_usage("sk_bad", success=False)
        self.store.record_usage("sk_bad", success=True)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEUROVA_SKILL_AUTO_RETIRE", None)
            result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)

        self.assertIn("sk_bad", result["retire_candidates"])
        self.assertEqual(result["retired"], [])
        self.assertEqual(self.registry.enabled_changes, [], "默认关：不自动禁用")
        self.assertEqual(self.service.disabled, [])

    def test_maintenance_retire_enabled_with_env(self):
        self.registry.register(_FakeSkill("sk_bad2"))
        for _ in range(12):
            self.store.record_usage("sk_bad2", success=False)
        self.store.record_usage("sk_bad2", success=True)

        with patch.dict(os.environ, {"NEUROVA_SKILL_AUTO_RETIRE": "1"}):
            result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)

        self.assertIn("sk_bad2", result["retired"])
        self.assertIn(("sk_bad2", False), self.registry.enabled_changes)
        self.assertIn("sk_bad2", self.service.disabled)


class BootstrapFlushWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        reset_skill_experience_store()

    def tearDown(self):
        self.tmp.cleanup()
        reset_skill_experience_store()

    def test_bootstrap_attaches_and_restores_store(self):
        from neurova.evolution import closed_loop

        exp_path = Path(self.tmp.name) / "skill_exp.json"
        env = {
            "NEUROVA_EVOLUTION_WEIGHTS": str(Path(self.tmp.name) / "w.json"),
            "NEUROVA_EVOLUTION_PATTERNS": str(Path(self.tmp.name) / "p.json"),
            "NEUROVA_EVOLUTION_LIFECYCLE": str(Path(self.tmp.name) / "l.json"),
            "NEUROVA_EVOLUTION_EXPERIENCE": str(Path(self.tmp.name) / "e.json"),
            "NEUROVA_EVOLUTION_SKILL_EXPERIENCE": str(exp_path),
        }
        exp_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "records": {
                        "sk_boot": [
                            {
                                "record_id": "r1",
                                "skill_id": "sk_boot",
                                "source": "improver",
                                "content": "boot guidance",
                                "context": "",
                                "created_at": 1000.0,
                                "merged": False,
                                "merged_version": "",
                            }
                        ]
                    },
                    "usage": {},
                    "archives": {},
                    "retired": {},
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, env):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                store = get_skill_experience_store()
                self.assertEqual(store._persist_path, exp_path)
                self.assertEqual(len(store.get_records("sk_boot")), 1)
            finally:
                closed_loop.reset_evolution_orchestrator()

    def test_flush_includes_skill_experience_store(self):
        from neurova.evolution import closed_loop

        exp_path = Path(self.tmp.name) / "skill_exp.json"
        env = {
            "NEUROVA_EVOLUTION_WEIGHTS": str(Path(self.tmp.name) / "w.json"),
            "NEUROVA_EVOLUTION_PATTERNS": str(Path(self.tmp.name) / "p.json"),
            "NEUROVA_EVOLUTION_LIFECYCLE": str(Path(self.tmp.name) / "l.json"),
            "NEUROVA_EVOLUTION_EXPERIENCE": str(Path(self.tmp.name) / "e.json"),
            "NEUROVA_EVOLUTION_SKILL_EXPERIENCE": str(exp_path),
        }
        with patch.dict(os.environ, env):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                get_skill_experience_store().record_experience("sk_f", "flush me")
                result = closed_loop.flush_evolution_persistence()
                self.assertTrue(result.get("skill_experience_store"))
                data = json.loads(exp_path.read_text(encoding="utf-8"))
                self.assertIn("sk_f", data["records"])
            finally:
                closed_loop.reset_evolution_orchestrator()


if __name__ == "__main__":
    unittest.main()
