"""P1-5 改进应用/回滚的写盘原子化

两条根因：
1. _save_manifest 直接 open(w) 截断——写一半崩溃 = manifest 清零
   （providers-config-loss 事故同型病灶）→ tmp + os.replace 原子写；
2. apply_improvement/revert 落盘失败只 warning、内存回滚缺失——
   盘上还是旧版、内存已是新版（重启回 1.0.0 的 split-brain 反向形态）
   → 落盘 False 即整体回滚内存态并返回 False。
"""

import pytest

from neurova.evolution.skill_improver import (
    ImprovementType,
    SkillImprovement,
    get_skill_improver,
    reset_skill_improver,
)
from tests.unit.skills.creation_helpers import register_proven_skill
from neurova.skills.skill_service import SkillService


class _FakeRegistry:
    def __init__(self):
        self.skills = {}

    def register_skill(self, skill):
        self.skills[skill.name] = skill

    def get_skill(self, name):
        return self.skills.get(name)


def _make_skill():
    from neurova.skills.models import Skill, SkillSource

    return Skill(
        id="gen_skill",
        name="gen_skill",
        version="1.0.0",
        description="",
        source=SkillSource.LOCAL,
        enabled=True,
        config={"tool_sequence": ["a", "b"]},
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_skill_improver()
    yield
    reset_skill_improver()


@pytest.fixture
def env(tmp_path):
    svc = SkillService(agent_id="atomic", skills_dir=str(tmp_path / "skills"))
    registry = _FakeRegistry()
    skill = _make_skill()
    registry.register_skill(skill)
    register_proven_skill(svc, "gen_skill", name="gen_skill", config={"tool_sequence": ["a", "b"]})
    return svc, registry, skill


# ── 原子写 ──────────────────────────────────────────────────


def test_save_manifest_atomic_via_tmp_replace(tmp_path, monkeypatch):
    import os as _os

    svc = SkillService(agent_id="aw", skills_dir=str(tmp_path / "s"))
    register_proven_skill(svc, "x1", name="x1")
    calls = []
    real_replace = _os.replace
    monkeypatch.setattr(_os, "replace", lambda a, b: (calls.append(a), real_replace(a, b))[1])
    assert svc._save_manifest() is True
    assert len(calls) == 1, "manifest 写入必须经 tmp+os.replace 原子替换"
    # 无 .tmp 残留
    leftovers = [p.name for p in (tmp_path / "s").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_manifest_failure_keeps_old_content_intact(tmp_path, monkeypatch):
    """replace 抛错 → 旧 manifest 内容完整（不截断），返回 False。"""
    import json as _json
    import os as _os

    svc = SkillService(agent_id="aw2", skills_dir=str(tmp_path / "s"))
    register_proven_skill(svc, "x1", name="x1")
    manifest = tmp_path / "s" / "manifest.json"
    before = manifest.read_text(encoding="utf-8")

    def _boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", _boom)
    assert svc._save_manifest() is False
    assert manifest.read_text(encoding="utf-8") == before


# ── update_auto_skill 落盘失败回滚 ──────────────────────────


def test_update_auto_skill_rolls_back_on_save_failure(env, monkeypatch):
    svc, _registry, _skill = env
    before = svc.get_skill_info("gen_skill")["version"]
    monkeypatch.setattr(svc, "_save_manifest", lambda: False)
    assert svc.update_auto_skill("gen_skill", version="9.9.9") is False
    assert svc.get_skill_info("gen_skill")["version"] == before


# ── apply_improvement 落盘失败整体回滚 ─────────────────────


def _proposal():
    return SkillImprovement(
        skill_id="gen_skill",
        improvement_type=ImprovementType.PARAMETER_TUNING,
        changes={"param": "timeout", "from": 5, "to": 10},
        reason="失败率过高",
        expected_impact=0.2,
    )


def test_apply_failure_rolls_back_memory_and_revisions(env, monkeypatch):
    svc, registry, skill = env
    monkeypatch.setattr(svc, "_save_manifest", lambda: False)
    improver = get_skill_improver()
    assert improver.apply_improvement(_proposal(), registry, skill_service=svc) is False
    # 内存态回到改进前：版本、config、revisions 全部还原
    assert skill.version == "1.0.0"
    assert not skill.config.get("improvements")
    assert not skill.config.get("revisions")


def test_apply_success_path_unaffected(env):
    svc, registry, skill = env
    improver = get_skill_improver()
    assert improver.apply_improvement(_proposal(), registry, skill_service=svc) is True
    assert skill.version == "1.0.1"
    assert svc.get_skill_info("gen_skill")["manifest"]["config"].get("improvements")


def test_revert_failure_rolls_back(env, monkeypatch):
    svc, registry, skill = env
    improver = get_skill_improver()
    assert improver.apply_improvement(_proposal(), registry, skill_service=svc) is True
    # 磁盘回滚失败 → 内存保持改进后状态、返回 False（不得半回滚）
    monkeypatch.setattr(svc, "_save_manifest", lambda: False)
    assert improver.revert_last_improvement("gen_skill", registry, skill_service=svc) is False
    assert skill.version == "1.0.1"
    assert skill.config.get("revisions"), "回滚失败时 revisions 必须保留（可重试回滚）"


def test_revert_success_still_works(env):
    svc, registry, skill = env
    improver = get_skill_improver()
    improver.apply_improvement(_proposal(), registry, skill_service=svc)
    assert improver.revert_last_improvement("gen_skill", registry, skill_service=svc) is True
    assert skill.version == "1.0.0"
