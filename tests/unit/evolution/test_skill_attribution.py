"""失败归因器测试 — 教训落到技能粒度（QP 对齐启发 #5）。

现状：SelfModelEngine 五算子产出的教训全部是工具粒度（subject=工具名），
消费面只有默认关的调控门——教训从未落到技能层，技能无法从失败中学习。

设计（对齐 jiuwenswarm review_feedback 归因模型，置信度阈值 0.7）：
- 从 MetaLedger 拉活跃工具级教训 → "工具→技能"倒排索引（registry 的
  tool_sequence 结构归因）→ 置信度过阈值后写入技能经验库（applied 记录
  立即生效，攒够参与重建）；
- 置信度 = 教训置信度 × 歧义惩罚(k) + 本技能使用统计佐证(±0.05)；
- 内容按算子模板归一化（不含波动数字）——同型教训重复反思不会刷屏经验库；
- 阈值下候选只上报不写入（可见但不生效）。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurova.evolution.skill_attribution import (
    attribute_failures_to_skills,
    build_tool_skill_index,
)
from neurova.evolution.skill_experience import (
    SkillExperienceStore,
    run_skill_experience_maintenance,
)

# 机制测试作用域：本文件验证归因/桥接机制本身——评审闸的待审流由
# test_skill_review_gate.py 覆盖，故此处统一关闭闸（治理后默认开）
_GATE_PATCHER = None


def setUpModule():
    global _GATE_PATCHER
    _GATE_PATCHER = patch.dict(os.environ, {"NEUROVA_SKILL_REVIEW_GATE": "0"})
    _GATE_PATCHER.start()


def tearDownModule():
    if _GATE_PATCHER:
        _GATE_PATCHER.stop()


def _lesson(subject, operator="drift", confidence=0.9, recommendation="avoid_tool", expires_at=None, finding=""):
    """构造与 SelfModelEngine.reflect 落台账同构的 lesson item。"""
    return {
        "kind": "lesson",
        "type": "monitoring",
        "content": f"lesson text for {subject}",
        "confidence": confidence,
        "metadata": {
            "subject": subject,
            "operator": operator,
            "condition": f"tool={subject}",
            "finding": finding or f"{operator} fired",
            "recommendation": recommendation,
            "text": f"工具 {subject} 教训",
            "evidence": {"success_rate": 0.42},
            "source": "template",
            "confidence": confidence,
            "expires_at": expires_at,
        },
    }


class _FakeSkill:
    def __init__(self, name, tool_sequence=None, description="base"):
        self.name = name
        self.description = description
        self.version = "1.0.0"
        self.config = {"tool_sequence": tool_sequence} if tool_sequence is not None else {}


class _FakeRegistry:
    def __init__(self, *skills):
        self.skills = {s.name: s for s in skills}

    def get_skill(self, name):
        return self.skills.get(name)

    def set_skill_enabled(self, name, enabled):
        return True


class _FakeLedger:
    def __init__(self, lessons):
        self._lessons = lessons

    def list_records(self, agent_id="", page=1, size=20, record_type=None, kind=None):
        items = [l for l in self._lessons if kind is None or l.get("kind") == kind]
        return {"items": items[: int(size)], "total": len(items)}


class ToolSkillIndexTest(unittest.TestCase):
    def test_index_normalizes_str_and_dict_steps(self):
        registry = _FakeRegistry(
            _FakeSkill("sk_str", tool_sequence=["web_search", "export"]),
            _FakeSkill("sk_dict", tool_sequence=[{"tool": "web_search"}, {"tool": "render"}]),
            _FakeSkill("sk_manual"),  # 无 tool_sequence
        )
        index = build_tool_skill_index(registry)
        self.assertEqual(sorted(index["web_search"]), ["sk_dict", "sk_str"])
        self.assertEqual(index["export"], ["sk_str"])
        self.assertEqual(index["render"], ["sk_dict"])
        self.assertNotIn("sk_manual", index["web_search"])


class AttributionTest(unittest.TestCase):
    def setUp(self):
        self.store = SkillExperienceStore()

    def test_single_tool_skill_attributed_and_written(self):
        """独占失败工具的技能：高置信归因，教训写为 applied 经验（立即生效）。"""
        registry = _FakeRegistry(
            _FakeSkill("sk_solo", tool_sequence=["web_search"]),
            _FakeSkill("sk_other", tool_sequence=["render"]),
        )
        ledger = _FakeLedger([_lesson("web_search", operator="drift", confidence=0.9)])
        result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)

        self.assertEqual(len(result["attributed"]), 1)
        attr = result["attributed"][0]
        self.assertEqual(attr["skill_id"], "sk_solo")
        self.assertGreaterEqual(attr["confidence"], 0.7)
        records = self.store.get_records("sk_solo")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "attribution")
        self.assertIn("web_search", records[0].content)

    def test_ambiguous_multi_skill_below_threshold(self):
        """失败工具被多个技能共用：歧义惩罚压到阈值下 → 只上报不写入。"""
        registry = _FakeRegistry(
            _FakeSkill("sk_a", tool_sequence=["web_search"]),
            _FakeSkill("sk_b", tool_sequence=["web_search", "export"]),
            _FakeSkill("sk_c", tool_sequence=[{"tool": "web_search"}]),
        )
        ledger = _FakeLedger([_lesson("web_search", confidence=0.8)])
        result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)

        self.assertEqual(result["attributed"], [])
        self.assertEqual(len(result["below_threshold"]), 3)
        for skill_id in ("sk_a", "sk_b", "sk_c"):
            self.assertEqual(self.store.get_records(skill_id), [])

    def test_corroboration_bonus_flips_borderline(self):
        """结构归因 borderline 时，技能自身使用统计失败率佐证 +0.05 翻过阈值。"""
        registry = _FakeRegistry(
            _FakeSkill("sk_x", tool_sequence=["tool_t"]),
            _FakeSkill("sk_y", tool_sequence=["tool_t", "other"]),
        )
        # sk_x 自身也在失败（3 次全败）——结构归因与行为数据互相印证
        for _ in range(3):
            self.store.record_usage("sk_x", success=False)
        ledger = _FakeLedger([_lesson("tool_t", confidence=0.8)])
        result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)

        attributed_skills = [a["skill_id"] for a in result["attributed"]]
        self.assertIn("sk_x", attributed_skills)  # 0.8×0.85+0.05=0.73 ≥ 0.7
        self.assertNotIn("sk_y", attributed_skills)  # 0.68 < 0.7
        self.assertEqual(len(self.store.get_records("sk_x")), 1)

    def test_expired_lesson_ignored(self):
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        ledger = _FakeLedger(
            [_lesson("web_search", expires_at="2000-01-01T00:00:00+00:00")]
        )
        result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)
        self.assertEqual(result["attributed"], [])
        self.assertEqual(result["lessons_read"], 0)

    def test_normalized_content_dedups_recurring_lessons(self):
        """同型教训重复反思（evidence 数字不同）→ 内容归一化 → 只写一条。"""
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        ledger1 = _FakeLedger(
            [_lesson("web_search", confidence=0.9, finding="rate 0.80 -> 0.45")]
        )
        ledger2 = _FakeLedger(
            [_lesson("web_search", confidence=0.9, finding="rate 0.80 -> 0.42")]
        )
        attribute_failures_to_skills(registry, store=self.store, ledger=ledger1)
        attribute_failures_to_skills(registry, store=self.store, ledger=ledger2)
        self.assertEqual(len(self.store.get_records("sk_solo")), 1)

    def test_operator_templates_differ(self):
        registry = _FakeRegistry(
            _FakeSkill("sk_a", tool_sequence=["tool_a"]), _FakeSkill("sk_b", tool_sequence=["tool_b"])
        )
        ledger = _FakeLedger(
            [_lesson("tool_a", operator="drift"), _lesson("tool_b", operator="sequence")]
        )
        attribute_failures_to_skills(registry, store=self.store, ledger=ledger)
        content_a = self.store.get_records("sk_a")[0].content
        content_b = self.store.get_records("sk_b")[0].content
        self.assertNotEqual(content_a, content_b)
        self.assertNotIn("0.42", content_a, "归一化内容不得携带波动数字")

    def test_unknown_tool_no_crash(self):
        """教训的 subject 不在任何技能序列里：安全跳过。"""
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        ledger = _FakeLedger([_lesson("mystery_tool")])
        result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)
        self.assertEqual(result["attributed"], [])
        self.assertEqual(result["below_threshold"], [])

    def test_env_threshold_override(self):
        import os
        from unittest.mock import patch

        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        ledger = _FakeLedger([_lesson("web_search", confidence=0.9)])
        with patch.dict(os.environ, {"NEUROVA_SKILL_ATTRIBUTION_MIN_CONFIDENCE": "0.95"}):
            result = attribute_failures_to_skills(registry, store=self.store, ledger=ledger)
        self.assertEqual(result["attributed"], [])
        self.assertEqual(len(result["below_threshold"]), 1)

    def test_no_ledger_skips_silently(self):
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        result = attribute_failures_to_skills(registry, store=self.store, ledger=None)
        self.assertEqual(result["attributed"], [])


class MaintenanceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.store = SkillExperienceStore()

    def test_maintenance_runs_attribution_phase(self):
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        service = type("S", (), {"update_auto_skill": lambda self, **kw: True, "disable_skill": lambda self, sid: {"success": True}})()
        ledger = _FakeLedger([_lesson("web_search", confidence=0.9)])
        result = run_skill_experience_maintenance(
            registry=registry, skill_service=service, store=self.store, ledger=ledger
        )
        self.assertEqual(len(result["attributed"]), 1)
        self.assertEqual(len(self.store.get_records("sk_solo")), 1)

    def test_attribution_feeds_rebuild_threshold(self):
        """归因写入的 applied 计入 pending——4 条存量 + 1 条归因即可触发重建。"""
        registry = _FakeRegistry(_FakeSkill("sk_due", tool_sequence=["web_search"]))
        updates = []
        service = type("S", (), {"update_auto_skill": lambda self, **kw: updates.append(kw) or True, "disable_skill": lambda self, sid: {"success": True}})()
        for i in range(4):
            self.store.record_experience("sk_due", f"g{i}")
        ledger = _FakeLedger([_lesson("web_search", confidence=0.9)])
        result = run_skill_experience_maintenance(
            registry=registry, skill_service=service, store=self.store, ledger=ledger
        )
        self.assertEqual(result["rebuilt"], ["sk_due"])
        self.assertTrue(updates)

    def test_maintenance_without_ledger_keeps_working(self):
        """ledger 缺席（默认）：归因跳过，重建/淘汰照常——向后兼容。"""
        registry = _FakeRegistry(_FakeSkill("sk_solo", tool_sequence=["web_search"]))
        service = type("S", (), {"update_auto_skill": lambda self, **kw: True, "disable_skill": lambda self, sid: {"success": True}})()
        result = run_skill_experience_maintenance(
            registry=registry, skill_service=service, store=self.store, ledger=None
        )
        self.assertEqual(result["attributed"], [])
        self.assertEqual(result["rebuilt"], [])


if __name__ == "__main__":
    unittest.main()
