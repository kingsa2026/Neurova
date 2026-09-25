"""改进落盘回归测试（遗留事项 ④：apply_improvement 只改内存对象，重启即回 1.0.0）

断点：AutoSkillImprover.apply_improvement/revert_last_improvement 只改
SkillRegistry 内存 Skill 对象的 config/version，SkillService 磁盘 manifest 无任何
更新调用——改进生效一次性，重启后版本号回 1.0.0、improvements 记录消失。

修复：
1. SkillService 新增 update_auto_skill（更新已存在自动技能的 version/config 并
   落盘；不存在返回 False）；
2. apply_improvement / revert_last_improvement 接受可选 skill_service，应用或
   回滚成功后把 config+version 同步到磁盘 manifest。
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from neurova.evolution.skill_improver import (
    FailureAnalysis,
    FailurePattern,
    ImprovementType,
    SkillImprovement,
    get_skill_improver,
    reset_skill_improver,
)
from tests.unit.skills.creation_helpers import register_proven_skill
from neurova.skills.skill_service import SkillService


def _make_skill(id="genetic_a_b", name="read_write_genetic_a_b", sequence=None):
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


def _registry():
    """真实 `SkillRegistry`（工单 014 的反掩盖要求）。

    原先这里是个 `_FakeRegistry`：按 `skill.name` 建键、只认 name —— 恰好把
    "注册表键域 ≠ 进化侧身份域"这个缺陷在测试里洗成绿色；再配上默认
    `id == name` 的假技能，`apply_improvement` 永远测不到取空。
    现在两者一起改：真注册表 + `id != name` 的技能。
    """
    from neurova.skill_system import SkillRegistry

    return SkillRegistry()


class TestUpdateAutoSkill:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = SkillService(agent_id="t", skills_dir=self.tmp)

    def test_update_existing_skill_persists(self):
        register_proven_skill(self.svc, 
            skill_id="genetic_a_b", name="genetic_a_b", config={"tool_sequence": ["a", "b"]}
        )
        ok = self.svc.update_auto_skill(
            skill_id="genetic_a_b", version="1.0.1", config={"tool_sequence": ["a", "b"], "improvements": [1]}
        )
        assert ok is True
        # 重新加载验证磁盘落盘
        svc2 = SkillService(agent_id="t", skills_dir=self.tmp)
        info = svc2.get_skill_info("genetic_a_b")
        assert info["version"] == "1.0.1"
        assert info["manifest"]["config"].get("improvements") == [1]

    def test_update_missing_skill_returns_false(self):
        assert self.svc.update_auto_skill(skill_id="nope", version="1.0.1") is False

    def test_update_keeps_source_auto(self):
        register_proven_skill(self.svc, skill_id="s1", name="s1", config={})
        self.svc.update_auto_skill(skill_id="s1", version="1.0.2", config={"x": 1})
        svc2 = SkillService(agent_id="t", skills_dir=self.tmp)
        info = svc2.get_skill_info("s1")
        assert info["manifest"]["source"] == "auto"


class TestApplyImprovementPersists:
    def setup_method(self):
        reset_skill_improver()
        self.tmp = tempfile.mkdtemp()
        self.svc = SkillService(agent_id="t", skills_dir=self.tmp)
        self.registry = _registry()
        self.manifest = _make_skill()
        self.registry.register_skill(self.manifest)
        # 被改进的是注册表里的运行时对象，manifest 只是账本记录；
        # 用工单 014 的身份键（id != name）取它——取不到即红。
        self.skill = self.registry.get_skill(self.manifest.id)
        assert self.skill is not None, f"身份键 {self.manifest.id} 未命中注册对象"
        register_proven_skill(self.svc,
            skill_id=self.manifest.id, name=self.manifest.name, version="1.0.0",
            config={"tool_sequence": ["a", "b"]},
        )

    def _proposal(self):
        imp = SkillImprovement(
            skill_id=self.manifest.id,
            improvement_type=ImprovementType.PARAMETER_TUNING,
            changes={"param": "timeout", "from": 5, "to": 10},
            reason="失败率过高",
            expected_impact=0.2,
        )
        return imp

    def test_apply_syncs_to_disk(self):
        improver = get_skill_improver()
        assert improver.apply_improvement(self._proposal(), self.registry, skill_service=self.svc) is True
        svc2 = SkillService(agent_id="t", skills_dir=self.tmp)
        info = svc2.get_skill_info(self.manifest.id)
        assert info["version"] == "1.0.1"
        # 改进留痕落在 revisions（工单 016 断点 b：不再写无人读取的 improvements）
        assert info["manifest"]["config"].get("revisions")

    def test_revert_syncs_to_disk(self):
        improver = get_skill_improver()
        improver.apply_improvement(self._proposal(), self.registry, skill_service=self.svc)
        assert improver.revert_last_improvement(self.manifest.id, self.registry, skill_service=self.svc) is True
        svc2 = SkillService(agent_id="t", skills_dir=self.tmp)
        info = svc2.get_skill_info(self.manifest.id)
        assert info["version"] == "1.0.0"
        assert not info["manifest"]["config"].get("revisions")

    def test_apply_without_service_still_works(self):
        """向后兼容：不传 skill_service 行为不变（仅内存）"""
        improver = get_skill_improver()
        assert improver.apply_improvement(self._proposal(), self.registry) is True
        assert self.skill.version == "1.0.1"
