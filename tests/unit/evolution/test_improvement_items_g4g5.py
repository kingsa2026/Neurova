"""§6 改进项组 4/5（C12/C13/D1/E2）契约测试。

C12 RSI 回执：apply_optimization 成功后追加 JSONL 回执（ts/parameter_path/
   old_value/new_value），优化前后可审计、可回溯。
C13 修订 hash：apply_improvement 前置 config 快照+hash 落入 config.revisions
   （有界 5 条），revert_last_improvement 可回滚最近一次改进。
D1 经验注入收敛：crystallized 与普通经验在注入装配处按内容键去重（结晶优先），
   两条管线不再重复注入同一条经验。
E2 隐私门控：AGENT_TOOL_RESULT 事件的 tool_messages 经脱敏——敏感键值
   （password/token/secret/api_key）脱敏，params 摘要化。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestC12RsiReceipts(unittest.TestCase):
    def test_apply_optimization_writes_receipt(self):
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

        system = MagicMock()
        system.decay_rate = 0.01
        manager = RSIIntegrationManager(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=system,
        )
        with tempfile.TemporaryDirectory() as td:
            receipts = str(Path(td) / "r.jsonl")
            with patch.dict("os.environ", {"NEUROVA_RSI_RECEIPTS": receipts}):
                ok = manager.apply_optimization("tool_memory.decay_rate", 0.05)
            self.assertTrue(ok)
            lines = [json.loads(l) for l in Path(receipts).read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            rec = lines[0]
            self.assertEqual(rec["parameter_path"], "tool_memory.decay_rate")
            self.assertEqual(rec["old_value"], 0.01)
            self.assertEqual(rec["new_value"], 0.05)
            self.assertIn("ts", rec)

    def test_failed_apply_no_receipt(self):
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

        manager = RSIIntegrationManager(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=MagicMock(),
        )
        with tempfile.TemporaryDirectory() as td:
            receipts = str(Path(td) / "r.jsonl")
            with patch.dict("os.environ", {"NEUROVA_RSI_RECEIPTS": receipts}):
                ok = manager.apply_optimization("nonexistent.param", 1.0)
            self.assertFalse(ok)
            self.assertFalse(Path(receipts).exists())


class TestC13RevisionHash(unittest.TestCase):
    def _registry_with_skill(self):
        from neurova.skills.models import Skill, SkillSource

        skill = Skill(
            id="genetic_a_b", name="genetic_a_b", version="1.0.0",
            description="d", author="genetic_engine", source=SkillSource.LOCAL,
            enabled=True, config={"tool_sequence": ["a", "b"]},
        )
        registry = MagicMock()
        registry.get_skill.return_value = skill
        registry.has_skill.return_value = True
        return registry, skill

    def test_apply_records_revision_snapshot(self):
        from neurova.evolution.skill_improver import (
            FailurePattern, ImprovementType, SkillImprovement, get_skill_improver, reset_skill_improver,
        )
        reset_skill_improver()
        registry, skill = self._registry_with_skill()
        imp = SkillImprovement(
            improvement_id="i1", skill_id="genetic_a_b",
            improvement_type=ImprovementType.PERFORMANCE,
            description="d", changes={"suggested_fix": "x"}, reason="r", expected_impact=0.2,
        )
        improver = get_skill_improver()
        self.assertTrue(improver.apply_improvement(imp, registry))
        revs = skill.config.get("revisions", [])
        self.assertEqual(len(revs), 1)
        rev = revs[0]
        self.assertEqual(rev["version_before"], "1.0.0")
        self.assertIn("config_before", rev)
        self.assertEqual(rev["config_before"]["tool_sequence"], ["a", "b"])
        self.assertIn("revision_hash_before", rev)

        # 第二次应用（不同提案）→ revisions 保留（上限 5 由实现保证）
        imp2 = SkillImprovement(
            improvement_id="i2", skill_id="genetic_a_b",
            improvement_type=ImprovementType.RELIABILITY,
            description="d2", changes={"suggested_fix": "y"}, reason="r2", expected_impact=0.1,
        )
        self.assertTrue(improver.apply_improvement(imp2, registry))

    def test_revert_last_improvement(self):
        from neurova.evolution.skill_improver import (
            ImprovementType, SkillImprovement, get_skill_improver, reset_skill_improver,
        )
        reset_skill_improver()
        registry, skill = self._registry_with_skill()
        improver = get_skill_improver()
        improver.apply_improvement(SkillImprovement(
            improvement_id="i1", skill_id="genetic_a_b",
            improvement_type=ImprovementType.PERFORMANCE,
            description="d", changes={"suggested_fix": "x"}, reason="r", expected_impact=0.2,
        ), registry)
        self.assertNotEqual(skill.version, "1.0.0")

        self.assertTrue(improver.revert_last_improvement("genetic_a_b", registry))
        self.assertEqual(skill.version, "1.0.0")
        self.assertEqual(skill.config["tool_sequence"], ["a", "b"])
        self.assertNotIn("improvements", skill.config)


class TestD1ExperienceDedup(unittest.TestCase):
    def test_crystallized_duplicates_normal_experience(self):
        """同内容经验（结晶产物与普通经验重复）只注入一次，且保留结晶优先级。"""
        from neurova.context.orchestrator import dedupe_experience_sources

        normal = [{"content": "使用 web_search 查天气成功了"}]
        crystal = [{"content": "使用 web_search 查天气成功了"}]
        merged = dedupe_experience_sources(normal, crystal)
        self.assertEqual(len(merged), 1)
        tag, content, prio = merged[0]
        self.assertEqual(tag, "[结晶经验] ")  # 结晶优先保留
        self.assertEqual(prio, 80)

    def test_different_content_both_kept(self):
        from neurova.context.orchestrator import dedupe_experience_sources

        merged = dedupe_experience_sources(
            [{"content": "经验A"}], [{"content": "结晶B"}]
        )
        self.assertEqual(len(merged), 2)


class TestE2PrivacyGate(unittest.TestCase):
    def test_sensitive_values_redacted(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        msgs = [{
            "tool_name": "web_fetch",
            "status": "success",
            "params": {"url": "https://x", "password": "hunter2", "api_key": "sk-123"},
        }]
        out = redact_tool_messages_for_channel(msgs)
        p = out[0]["params"]
        self.assertEqual(p["url"], "https://x")
        self.assertNotIn("hunter2", json.dumps(out))
        self.assertNotIn("sk-123", json.dumps(out))

    def test_private_visibility_drops_params(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        msgs = [{
            "tool_name": "computer_shell",
            "params": {"command": "ls"},
            "visibility": "private",
        }]
        out = redact_tool_messages_for_channel(msgs)
        self.assertNotIn("params", out[0])
        self.assertEqual(out[0]["tool_name"], "computer_shell")

    def test_no_params_untouched(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        msgs = [{"tool_name": "weather", "status": "success"}]
        out = redact_tool_messages_for_channel(msgs)
        self.assertEqual(out[0], msgs[0])


if __name__ == "__main__":
    unittest.main()
