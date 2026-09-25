"""工单 015 · 技能自动淘汰开关收进治理设置。

`NEUROVA_SKILL_AUTO_RETIRE=1 才执行禁用` 是生产无写入方的裸 env：淘汰依据
（使用统计）早就算得出来，执行闸门却永远关着。收进治理面后与
`metacog_gate_enabled` 同口径：**env 显式 0 强制关 > env 显式 1 强制开 >
治理设置 > 内置默认关**，三个方向都要断言。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurova.evolution.skill_experience import (
    get_skill_experience_store,
    reset_skill_experience_store,
    run_skill_experience_maintenance,
)

_RETIRE_ENV = "NEUROVA_SKILL_AUTO_RETIRE"
_RETIRE_KEY = "skill_auto_retire_enabled"


class _FakeSkill:
    def __init__(self, name):
        self.name = name
        self.description = "base desc"
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
        self.disabled = []

    def disable_skill(self, skill_id):
        self.disabled.append(skill_id)
        return {"success": True}


class SkillAutoRetireGovernanceTest(unittest.TestCase):
    def setUp(self):
        reset_skill_experience_store()
        self.registry = _FakeRegistry()
        self.service = _FakeSkillService()
        self.store = get_skill_experience_store()
        self._work = tempfile.TemporaryDirectory()
        self.settings_file = os.path.join(self._work.name, "governance_settings.json")
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop(_RETIRE_ENV, None)
        self._settings = patch(
            "neurova.security.governance_settings.settings_path",
            return_value=Path(self.settings_file),
        )
        self._settings.start()

    def tearDown(self):
        self._settings.stop()
        self._env.stop()
        self._work.cleanup()
        reset_skill_experience_store()

    def _given_retirement_candidate(self, skill_name):
        """失败 12 次 + 成功 1 次 ⇒ 落入淘汰候选（依据可见，与开关无关）。"""
        self.registry.register(_FakeSkill(skill_name))
        for _ in range(12):
            self.store.record_usage(skill_name, success=False)
        self.store.record_usage(skill_name, success=True)

    def _set_governance(self, enabled):
        with open(self.settings_file, "w", encoding="utf-8") as fh:
            json.dump({_RETIRE_KEY: enabled}, fh)

    def test_default_off_only_reports_candidates(self):
        """反向锁：收口不得改变现网默认——没有配置时仍只上报、不自动禁用。"""
        self._given_retirement_candidate("sk_default_off")
        result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_default_off", result["retire_candidates"])
        self.assertEqual(result["retired"], [])
        self.assertEqual(self.registry.enabled_changes, [])
        self.assertEqual(self.service.disabled, [])

    def test_governance_true_enables_retirement_without_env(self):
        """生产可写入口：治理设置 True 即执行淘汰（此前只有 env 能开，等于永关）。"""
        self._set_governance(True)
        self._given_retirement_candidate("sk_gov_on")
        result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_gov_on", result["retired"])
        self.assertIn(("sk_gov_on", False), self.registry.enabled_changes)
        self.assertIn("sk_gov_on", self.service.disabled)

    def test_env_one_forces_retire_over_governance_false(self):
        """方向②：env 显式 1 压过治理 False。"""
        self._set_governance(False)
        self._given_retirement_candidate("sk_env_on")
        with patch.dict(os.environ, {_RETIRE_ENV: "1"}):
            result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_env_on", result["retired"])

    def test_env_zero_forces_off_over_governance_true(self):
        """方向①：env 显式 0 压过治理 True（运维临时止血的路还在）。"""
        self._set_governance(True)
        self._given_retirement_candidate("sk_env_off")
        with patch.dict(os.environ, {_RETIRE_ENV: "0"}):
            result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_env_off", result["retire_candidates"])
        self.assertEqual(result["retired"], [], "env 显式关闸必须退回报上报态")
        self.assertEqual(self.registry.enabled_changes, [])

    def test_candidates_still_visible_when_disabled(self):
        """开关只管执行、不管观测：关着也要看得见候选。"""
        self._set_governance(False)
        self._given_retirement_candidate("sk_visible")
        result = run_skill_experience_maintenance(registry=self.registry, skill_service=self.service)
        self.assertIn("sk_visible", result["retire_candidates"])
        self.assertEqual(result["retired"], [])


if __name__ == "__main__":
    unittest.main()
