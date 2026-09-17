"""Wave 3 — SkillService 生命周期接口接线测试。

record_skill_usage 须 seed 状态字段(state/pinned/created_by/created_at_ms);
iter_skills / set_skill_lifecycle_state / archive_skill 供
neurova.evolution.skill_lifecycle.apply_transitions 消费。
归档 = 物理移到 .archive/,永不删除。
"""

import json

import pytest

from neurova.evolution.skill_lifecycle import apply_transitions
from tests.unit.skills.creation_helpers import register_proven_skill
from neurova.skills.skill_service import SkillService


@pytest.fixture
def svc(tmp_path):
    return SkillService(agent_id="lifecycle-test", skills_dir=str(tmp_path / "skills"))


class TestUsageSeedsLifecycleFields:
    def test_record_usage_seeds_fields(self, svc):
        register_proven_skill(svc, "s1", "Skill One", description="d")
        assert svc.record_skill_usage("s1")
        usage = svc._skills["s1"]["usage"]
        assert usage["state"] == "active"
        assert usage["pinned"] is False
        assert usage["created_by"] == "agent"  # source=auto → agent
        assert usage["last_activity_at_ms"] > 0

    def test_marketplace_skill_created_by_hub(self, svc):
        svc._skills["m1"] = {"id": "m1", "source": "marketplace", "usage": {}}
        svc.record_skill_usage("m1")
        assert svc._skills["m1"]["usage"]["created_by"] == "hub"

    def test_unknown_skill_rejected(self, svc):
        assert not svc.record_skill_usage("nope")

    def test_fields_persisted_to_manifest(self, svc, tmp_path):
        register_proven_skill(svc, "s1", "Skill One", description="d")
        svc.record_skill_usage("s1")
        manifest = json.loads(
            (tmp_path / "skills" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["s1"]["usage"]["state"] == "active"


class TestLifecycleInterfaces:
    def test_iter_and_set_state(self, svc):
        register_proven_skill(svc, "s1", "Skill One", description="d")
        svc.record_skill_usage("s1")
        ids = [sid for sid, _ in svc.iter_skills()]
        assert "s1" in ids
        assert svc.set_skill_lifecycle_state("s1", "stale")
        assert svc._skills["s1"]["usage"]["state"] == "stale"

    def test_set_state_unknown_skill(self, svc):
        assert not svc.set_skill_lifecycle_state("nope", "stale")


class TestArchive:
    def test_archive_moves_dir_to_dot_archive(self, svc, tmp_path):
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "disk-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "manifest.json").write_text("{}", encoding="utf-8")
        svc._skills["disk-skill"] = {
            "id": "disk-skill", "path": str(skill_dir), "usage": {},
        }
        result = svc.archive_skill("disk-skill")
        assert result["success"] and result["moved"]
        assert not skill_dir.exists()
        assert (skills_dir / ".archive" / "disk-skill").is_dir()
        assert svc._skills["disk-skill"]["usage"]["state"] == "archived"
        # 归档后路径指向 .archive 内(可恢复)
        assert ".archive" in svc._skills["disk-skill"]["path"]

    def test_archive_never_deletes_content(self, svc, tmp_path):
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "disk-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# 内容", encoding="utf-8")
        svc._skills["disk-skill"] = {"id": "disk-skill", "path": str(skill_dir), "usage": {}}
        svc.archive_skill("disk-skill")
        archived_md = (skills_dir / ".archive" / "disk-skill" / "SKILL.md")
        assert archived_md.read_text(encoding="utf-8") == "# 内容"

    def test_archive_metadata_only_skill(self, svc):
        """无磁盘目录的 auto 技能:只改状态,不搬文件。"""
        register_proven_skill(svc, "s1", "Skill One", description="d")
        result = svc.archive_skill("s1")
        assert result["success"] and not result["moved"]
        assert svc._skills["s1"]["usage"]["state"] == "archived"

    def test_archive_unknown_skill(self, svc):
        assert not svc.archive_skill("nope")["success"]


class TestSeedOnFirstSight:
    def test_seed_persists_created_at_anchor(self, svc):
        """首见播种落盘 created_at_ms(时钟从此开始),否则永不活跃技能不进老化通道。"""
        register_proven_skill(svc, "s1", "Skill One", description="d")
        assert "usage" not in svc._skills["s1"]
        assert svc.seed_skill_usage("s1")
        usage = svc._skills["s1"]["usage"]
        assert usage["state"] == "active"
        assert usage["use_count"] == 0
        assert usage["created_at_ms"] > 0
        assert usage["created_by"] == "agent"
        # 落盘可重载
        from neurova.skills.skill_service import SkillService

        svc2 = SkillService(agent_id="lifecycle-test", skills_dir=str(svc.skills_dir))
        assert svc2.get_skill_info("s1")["usage"]["created_at_ms"] > 0

    def test_apply_transitions_seeds_then_ages(self, svc):
        """两轮时间旅行:首轮仅 seed,拨老 created_at 后次轮归档。"""
        import time

        from neurova.evolution.skill_lifecycle import apply_transitions

        register_proven_skill(svc, "s1", "Skill One", description="d")
        now = int(time.time() * 1000)
        counts1 = apply_transitions(svc, now_ms=now)
        assert counts1["seeded"] == 1
        assert svc._skills["s1"]["usage"]["state"] == "active"  # 首见绝不动

        # 把锚点拨老 40 天(模拟长期无活动),第二轮应归档
        svc._skills["s1"]["usage"]["created_at_ms"] = now - 40 * 86_400_000
        counts2 = apply_transitions(svc, now_ms=now + 86_400_000)
        assert counts2["archived"] == 1

    def test_seed_unknown_skill_false(self, svc):
        assert not svc.seed_skill_usage("ghost")

class TestEndToEndWithLifecycle:
    def test_apply_transitions_archives_old_auto_skill(self, svc, tmp_path):
        """老化的 agent 技能经 apply_transitions 走到 archived(真库接线)。"""
        import time

        register_proven_skill(svc, "old-skill", "Old", description="d")
        svc.record_skill_usage("old-skill")
        # 把活动锚拨回 40 天前
        usage = svc._skills["old-skill"]["usage"]
        usage["last_activity_at_ms"] = int(time.time() * 1000) - 40 * 86_400_000
        svc._save_manifest()

        counts = apply_transitions(svc)
        assert counts["checked"] >= 1
        assert svc._skills["old-skill"]["usage"]["state"] == "archived"

    def test_marketplace_skill_protected_from_lifecycle(self, svc):
        """hub 来源技能不该被生命周期迁移(保护语义 2,真库接线)。"""
        import time

        svc._skills["hub-skill"] = {
            "id": "hub-skill", "source": "marketplace",
            "usage": {"state": "active", "use_count": 1, "pinned": False,
                      "created_by": "hub",
                      "last_activity_at_ms": int(time.time() * 1000) - 100 * 86_400_000,
                      "created_at_ms": int(time.time() * 1000) - 100 * 86_400_000},
        }
        apply_transitions(svc)
        assert svc._skills["hub-skill"]["usage"]["state"] == "active"
