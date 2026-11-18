"""对照批 B11：技能 manifest 渠道限定 + 环境依赖过滤。

- manifest 渠道限定：config.channels 非空时，本轮渠道（turn_context 盖章）
  不在名单 → 本轮不注入；渠道未盖章时不过滤（既有行为零变化）。
- require_envs：声明的环境变量缺失 → 不注入并点名（不静默）。
- SkillManifestEntry 落三字段：channels/require_envs/preload。
"""

from types import SimpleNamespace

import pytest

from neurova.core import turn_context
from neurova.skills.manifest_entry import SkillManifestEntry
from neurova.skills.skill_injection import select_skills_for_turn


def _skill(name: str, config: dict) -> tuple:
    return (SimpleNamespace(name=name, enabled=True, config=config), None)


def _skills(*entries) -> dict:
    return {name: obj for name, obj in entries}


@pytest.fixture(autouse=True)
def _resetChannel():
    turn_context.set_turn_channel(None)
    yield
    turn_context.set_turn_channel(None)


class TestChannelFilter:

    def test_channel_mismatch_excluded(self):
        turn_context.set_turn_channel("telegram")
        skills = _skills(
            ("web", _skill("web", {"channels": ["console"]})),
            ("im", _skill("im", {"channels": ["telegram"]})),
        )
        picked = select_skills_for_turn(skills, "随便聊聊")
        assert "im" in picked and "web" not in picked

    def test_no_channel_declared_always_included(self):
        turn_context.set_turn_channel("telegram")
        skills = _skills(("legacy", _skill("legacy", {})))
        assert "legacy" in select_skills_for_turn(skills, "随便聊聊")

    def test_no_turn_channel_keeps_legacy_behavior(self):
        # 渠道未盖章（如 API 轮）：带渠道限定的技能不因此出局（零行为变化）
        skills = _skills(("web", _skill("web", {"channels": ["console"]})))
        assert "web" in select_skills_for_turn(skills, "随便聊聊")


class TestRequireEnvs:

    def test_missing_env_excluded(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEST_SKILL_TOKEN", raising=False)
        turn_context.set_turn_channel("console")
        skills = _skills(
            ("needs", _skill("needs", {"require_envs": ["NEUROVA_TEST_SKILL_TOKEN"]})),
            ("free", _skill("free", {})),
        )
        picked = select_skills_for_turn(skills, "随便聊聊")
        assert "needs" not in picked and "free" in picked

    def test_present_env_included(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEST_SKILL_TOKEN", "t-1")
        turn_context.set_turn_channel("console")
        skills = _skills(
            ("needs", _skill("needs", {"require_envs": ["NEUROVA_TEST_SKILL_TOKEN"]})),
        )
        assert "needs" in select_skills_for_turn(skills, "随便聊聊")


class TestManifestEntryFields:

    def test_defaults_keep_legacy_behavior(self):
        entry = SkillManifestEntry(id="s", name="s")
        assert entry.channels == [] and entry.require_envs == []
        assert entry.preload is False
