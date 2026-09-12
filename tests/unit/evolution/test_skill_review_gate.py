"""技能评审闸治理收紧测试（QP 对齐启发 #3，2026-09-12）。

C10 评审闸默认从关改为开：改行为的进化产物（自动封装技能/打包技能/
遗传技能/自动化 applied 经验）默认先进待审，经审批面激活——对齐
jiuwenswarm auto_save 默认 false 哲学。NEUROVA_SKILL_REVIEW_GATE=0 回退旧行为。
"""

import unittest
from unittest.mock import MagicMock, patch

from neurova.evolution.skill_review_gate import skill_review_gate_enabled


class GateHelperTest(unittest.TestCase):
    def test_default_on(self):
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("NEUROVA_SKILL_REVIEW_GATE", None)
            self.assertTrue(skill_review_gate_enabled())

    def test_explicit_off(self):
        with patch.dict("os.environ", {"NEUROVA_SKILL_REVIEW_GATE": "0"}):
            self.assertFalse(skill_review_gate_enabled())


class AutoSkillBuilderGateTest(unittest.TestCase):
    def test_builder_gate_default_on(self):
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder

        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("NEUROVA_SKILL_REVIEW_GATE", None)
            builder = AutoSkillBuilder()
            self.assertTrue(builder._review_gate, "治理收紧：评审闸默认开")

    def test_builder_gate_explicit_off(self):
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder

        with patch.dict("os.environ", {"NEUROVA_SKILL_REVIEW_GATE": "0"}):
            builder = AutoSkillBuilder()
            self.assertFalse(builder._review_gate)


class SkillPackerGateTest(unittest.TestCase):
    def _packer(self, gate_env=None):
        import tempfile

        from neurova.skill.skill_packer import SkillPacker

        env = {"NEUROVA_SKILL_REVIEW_GATE": gate_env} if gate_env is not None else {}
        env = {k: v for k, v in env.items() if v is not None}
        with patch.dict("os.environ", env, clear=False):
            import os as _os

            _os.environ.pop("NEUROVA_SKILL_REVIEW_GATE", None) if gate_env is None else None
            return SkillPacker(storage_dir=tempfile.mkdtemp())

    def test_pack_goes_pending_by_default(self):
        packer = self._packer()  # 默认闸开
        packer._write_to_toolmemory = MagicMock()
        packer._record_experience = MagicMock()
        sid = packer.pack_skill(name="gated_skill", description="d")
        self.assertTrue(packer._skills[sid].metadata.get("review_pending"))
        packer._write_to_toolmemory.assert_not_called()
        self.assertEqual(len(packer.list_pending_skills()), 1)

    def test_approve_activates(self):
        packer = self._packer()
        packer._write_to_toolmemory = MagicMock()
        packer._record_experience = MagicMock()
        sid = packer.pack_skill(name="gated_skill", description="d")
        self.assertTrue(packer.approve_skill(sid))
        packer._write_to_toolmemory.assert_called_once()
        packer._record_experience.assert_called_once()
        self.assertEqual(packer.list_pending_skills(), [])
        self.assertFalse(packer._skills[sid].metadata.get("review_pending"))

    def test_reject_removes(self):
        packer = self._packer()
        sid = packer.pack_skill(name="gated_skill", description="d")
        self.assertTrue(packer.reject_skill(sid))
        self.assertNotIn(sid, packer._skills)

    def test_gate_off_direct_activate(self):
        packer = self._packer(gate_env="0")
        packer._write_to_toolmemory = MagicMock()
        packer._record_experience = MagicMock()
        sid = packer.pack_skill(name="direct_skill", description="d")
        packer._write_to_toolmemory.assert_called_once()
        self.assertEqual(packer.list_pending_skills(), [])


class GeneticGateTest(unittest.TestCase):
    def test_genetic_registers_disabled_when_gated(self):
        from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        gen = ToolGeneticEngine()
        gen.add_to_population(
            ToolGenotype(tool_sequence=["search_tool", "file_tool"], success_rate=0.9, reuse_count=10)
        )
        with patch(
            "neurova.evolution.skill_review_gate.skill_review_gate_enabled",
            return_value=True,
        ):
            registered = gen.register_to_skill_registry(registry)
        self.assertEqual(registered, 1)
        self.assertFalse(registry.set_skill_enabled.__self__ is None)  # registry 完好
        skill = registry.get_skill("genetic_search_tool_file_tool")
        self.assertIsNotNone(skill)
        from neurova.skill_system_module_standalone import SkillStatus

        self.assertEqual(skill.status, SkillStatus.INACTIVE, "评审闸开启：遗传产物注册即禁用")

    def test_genetic_registers_active_when_gate_off(self):
        from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        gen = ToolGeneticEngine()
        gen.add_to_population(
            ToolGenotype(tool_sequence=["search_tool", "file_tool"], success_rate=0.9, reuse_count=10)
        )
        with patch(
            "neurova.evolution.skill_review_gate.skill_review_gate_enabled",
            return_value=False,
        ):
            gen.register_to_skill_registry(registry)
        skill = registry.get_skill("genetic_search_tool_file_tool")
        from neurova.skill_system_module_standalone import SkillStatus

        self.assertEqual(skill.status, SkillStatus.ACTIVE)


class ExperiencePendingGateTest(unittest.TestCase):
    def setUp(self):
        from neurova.evolution.skill_experience import SkillExperienceStore

        self.store = SkillExperienceStore()
        self.registry = MagicMock()
        skill = MagicMock()
        skill.config = {}
        skill.description = "base"
        self.registry.get_skill.return_value = skill
        self.skill = skill

    def test_automated_source_goes_pending_by_default(self):
        rec = self.store.record_experience(
            "sk_a", "先探测再写入", source="improver", registry=self.registry
        )
        self.assertIsNotNone(rec)
        # 待审：不注入、不计入重建阈值
        self.registry.get_skill.return_value.config.get("base_description")
        self.assertEqual(self.store.get_records("sk_a"), [])
        self.assertEqual(len(self.store.list_pending_experiences()), 1)

    def test_manual_source_direct_apply(self):
        rec = self.store.record_experience(
            "sk_a", "人工录入指引", source="manual", registry=self.registry
        )
        self.assertIsNotNone(rec)
        self.assertEqual(len(self.store.get_records("sk_a")), 1)

    def test_approve_applies_and_counts_toward_rebuild(self):
        rec = self.store.record_experience(
            "sk_a", "指引一", source="attribution", registry=self.registry
        )
        self.assertTrue(self.store.approve_experience(rec.record_id, registry=self.registry))
        self.assertEqual(len(self.store.get_records("sk_a")), 1)
        self.assertIn("指引一", self.skill.description)
        self.assertEqual(self.store.pending_rebuild("sk_a"), 1)

    def test_reject_drops(self):
        rec = self.store.record_experience("sk_a", "指引二", source="attribution")
        self.assertTrue(self.store.reject_experience(rec.record_id))
        self.assertEqual(self.store.list_pending_experiences(), [])
        self.assertEqual(self.store.get_records("sk_a"), [])


if __name__ == "__main__":
    unittest.main()
