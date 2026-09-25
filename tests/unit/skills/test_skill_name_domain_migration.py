# -*- coding: utf-8 -*-
"""存量库名字域迁移（Issue #189 残留 · ADR 0019「同名覆盖：出声不硬拒」留的口）。

病灶链：`SkillRegistry` 按 `skill.name` 建键（ADR 0017 定的键域），而**历史
manifest** 里 `ai_tool` / `general_tool` 这类名字被多条不同身份（`synth_*`）的
条目共用——注册表只留得住一条，其余 7 条在工具面上**静默消失**。
上一批只修了**产生侧**（新合成名携带身份），存量库按 ADR 0019 只出声不硬拒，
迁移留给本单。

本单的口径：**名字域 = 身份的函数**（同 name 不同身份 ⇒ 派生名携带身份），
判据只写一份（`neurova/skills/skill_name_domain.py`），三处消费同一份：

1. 存量库迁移（`migrateNameDomain`）：就地收敛 + 落盘 + 幂等；
2. 装配（`restore_market_skills_from_service`）：装机前收敛，工具面不再丢技能；
3. 新写入（`SkillService` 写入口）：按构造成立，名字域不再退化。

验收判据是**真装配链路上技能没少**（`registry.skills` 条数与身份可取），
不是"manifest 字段变了"。
"""

from __future__ import annotations

import copy
import json

from neurova.skill_system import SkillRegistry
from neurova.skills.skill_name_domain import (
    TOOL_NAME_MAX_LEN,
    claimUniqueName,
    isLegalToolName,
    migrateManifestNames,
    recountManifestCollisions,
)

COLLIDING_NAME = "general_tool"
LEGACY_NAMES = ("general_tool", "ai_tool")


def _legacy_payload() -> dict:
    """审计记载的存量形状：`general_tool` 8 条 + `ai_tool` 2 条，身份各不相同。"""
    payload: dict = {}
    index = 0
    for name, count in ((COLLIDING_NAME, 8), ("ai_tool", 2)):
        for _ in range(count):
            sid = f"synth_{index:04d}"
            payload[sid] = {
                "id": sid,
                "name": name,
                "description": f"历史生成器遗留 #{index}",
                "enabled": True,
                "installed_at": "2026-01-01T00:00:00",
                "path": "",
                "manifest": {
                    "source": "synthesized",
                    "config": {
                        "tool_sequence": [{"tool": "read_file", "params": {"id": sid}}]
                    },
                },
            }
            index += 1
    payload["_skill_aliases"] = {"synth_legacy": "synth_0000"}
    return payload


def _names(payload: dict) -> list:
    return [
        str(entry.get("name"))
        for key, entry in payload.items()
        if key != "_skill_aliases" and isinstance(entry, dict)
    ]


class TestUniqueNameJudgement:
    """名字域唯一的判据（单一事实源）。"""

    def test_legalToolNameContract(self):
        assert isLegalToolName("general_tool_2")
        assert isLegalToolName("a" * TOOL_NAME_MAX_LEN)
        assert not isLegalToolName("")
        assert not isLegalToolName("a" * (TOOL_NAME_MAX_LEN + 1))
        assert not isLegalToolName("工具名")
        assert not isLegalToolName("a b")

    def test_freeNameStaysUntouched(self):
        """名字空闲时零 churn——迁移不得顺手改无关条目。"""
        assert claimUniqueName("search_file", "synth_ab12", {"other_tool"}) == "search_file"

    def test_takenNameCarriesTheIdentity(self):
        claimed = claimUniqueName("general_tool", "synth_ab12cd34", {"general_tool"})
        assert claimed != "general_tool"
        assert "synth_ab12cd34" in claimed, "派生名没携带身份，下次装配还会撞回同一个 name"
        assert isLegalToolName(claimed)

    def test_derivedNameAvoidsSecondCollision(self):
        taken = {"general_tool", "general_tool_synth_ab12cd34"}
        claimed = claimUniqueName("general_tool", "synth_ab12cd34", taken)
        assert claimed not in taken
        assert isLegalToolName(claimed)

    def test_hostileBaseNameStillYieldsALegalToolName(self):
        """存量里若有非法字符/超长/空白的名字，**派生**名仍须满足工具名契约。"""
        for base in ("工具名字", "x" * 200, "", "a b c"):
            claimed = claimUniqueName(base, "synth_ab12cd34", {base})
            assert isLegalToolName(claimed), f"派生名不合法: {claimed!r}（base={base!r}）"
            assert "synth_ab12cd34" in claimed

    def test_uniqueNameIsKeptRegardlessOfCharset(self):
        """唯一即保留：`本地版` / `Web Search` 这类既有名字不被顺手改字形。"""
        assert claimUniqueName("本地版", "skill_deploy", set()) == "本地版"
        assert claimUniqueName("Web Search", "web-search", {"other"}) == "Web Search"

    def test_missingIdentityIsNotFaked(self):
        """身份缺席：不伪造身份（与 NL 合成臂同纪律），原样返回由调用方出声。"""
        assert claimUniqueName("general_tool", "", {"general_tool"}) == "general_tool"


class TestManifestMigration:
    """存量 manifest 的名字域迁移。"""

    def test_legacySharedNameEntriesBecomeDistinct(self):
        payload = _legacy_payload()
        report = migrateManifestNames(payload)
        assert report["renamed_count"] == 8, (
            f"10 条里同 name 不同身份的额外条目数是 8（每组保留先到者）：{report}"
        )
        assert sorted(_names(payload)) == sorted(set(_names(payload))), "迁移后名字域仍不唯一"
        assert len(_names(payload)) == 10, "迁移把条目弄丢了"

    def test_identitiesArePreserved(self):
        payload = _legacy_payload()
        migrateManifestNames(payload)
        assert payload["synth_0003"]["id"] == "synth_0003"
        assert "synth_0003" in payload["synth_0003"]["name"]

    def test_migrationIsIdempotent(self):
        payload = _legacy_payload()
        migrateManifestNames(payload)
        snapshot = copy.deepcopy(payload)
        second = migrateManifestNames(payload)
        assert second["renamed_count"] == 0, "重跑仍有改名——迁移不幂等"
        assert payload == snapshot

    def test_distinctNamesAreNotTouched(self):
        payload = {
            "a": {"id": "a", "name": "alpha_tool"},
            "b": {"id": "b", "name": "beta_tool"},
        }
        assert migrateManifestNames(payload)["renamed_count"] == 0
        assert _names(payload) == ["alpha_tool", "beta_tool"]

    def test_aliasTableIsNotASkillEntry(self):
        payload = _legacy_payload()
        migrateManifestNames(payload)
        assert payload["_skill_aliases"] == {"synth_legacy": "synth_0000"}

    def test_recountAgreesWithMigration(self):
        payload = _legacy_payload()
        before = recountManifestCollisions(payload)["collision_count"]
        migrateManifestNames(payload)
        after = recountManifestCollisions(payload)["collision_count"]
        assert (before, after) == (8, 0)


class TestServiceMigrationPersistsToDisk:
    """服务层迁移：就地收敛 + 落盘（写入 → 读取 → 反馈 → 再写入）。"""

    @staticmethod
    def _service(tmp_path, agent_id="agent-name-domain"):
        from neurova.skills.skill_service import SkillService

        skills_dir = tmp_path / "agents" / agent_id / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "manifest.json").write_text(
            json.dumps(_legacy_payload(), ensure_ascii=False), encoding="utf-8"
        )
        return SkillService(agent_id=agent_id, skills_dir=str(skills_dir))

    def test_openingTheLibraryConvergesItOnDisk(self, tmp_path):
        """库被打开的那一刻就收敛（名空间唯一是库自身的不变量）。"""
        service = self._service(tmp_path)
        on_disk = json.loads(
            (service.skills_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert sorted(_names(on_disk)) == sorted(set(_names(on_disk)))
        assert recountManifestCollisions(on_disk)["collision_count"] == 0
        assert len(_names(on_disk)) == 10, "收敛把条目弄丢了"

    def test_explicitMigrationIsIdempotent(self, tmp_path):
        service = self._service(tmp_path)
        assert service.migrateNameDomain()["renamed_count"] == 0
        first = (service.skills_dir / "manifest.json").read_text(encoding="utf-8")
        service.migrateNameDomain()
        assert (service.skills_dir / "manifest.json").read_text(encoding="utf-8") == first

    def test_migrationReportTellsHowManyWereRenamed(self, tmp_path):
        """报告读数与"改了几条"一致（收敛的实测发生在构造时，此处单独重放一次）。"""
        from neurova.skills.skill_name_domain import migrateManifestNames

        payload = _legacy_payload()
        assert migrateManifestNames(payload)["renamed_count"] == 8
        service = self._service(tmp_path)
        assert service.migrateNameDomain()["persisted"] is True


class TestAssemblyKeepsEveryLegacySkill:
    """验收判据：真装配链路上，存量库里的技能一个都不少。"""

    @staticmethod
    def _assembled(tmp_path):
        from neurova.skills.market_registry import restore_market_skills_from_service

        service = TestServiceMigrationPersistsToDisk._service(tmp_path)
        registry = SkillRegistry()
        restored = restore_market_skills_from_service(service, registry)
        return service, registry, restored

    def test_everyEntryIsOnTheToolFace(self, tmp_path):
        service, registry, restored = self._assembled(tmp_path)
        assert restored == 10, f"装配少装了技能：{restored}"
        assert len(registry.skills) == 10, (
            f"工具面上只剩 {len(registry.skills)} 条——同名条目仍在静默顶替："
            f"{sorted(registry.skills)}"
        )

    def test_registryReportsNoCollisionAfterAssembly(self, tmp_path):
        _, registry, _ = self._assembled(tmp_path)
        assert getattr(registry, "_name_collision_count", 0) == 0, (
            "装配后注册表仍报同名覆盖——存量名字域没收敛"
        )

    def test_everyIdentityIsStillReachable(self, tmp_path):
        service, registry, _ = self._assembled(tmp_path)
        missing = [
            sid for sid, _ in service.iter_skills() if registry.get_skill(sid) is None
        ]
        assert missing == [], f"身份域取不到技能（血缘断了）：{missing}"


class TestCreationBoundaryClaimsTheName:
    """新写入按构造成立：名字域被占了就派生携带身份的名字，下次装配不再撞回。"""

    @staticmethod
    def _service(tmp_path):
        from neurova.skills.skill_service import SkillService

        return SkillService(agent_id="agent-claim", skills_dir=str(tmp_path / "skills"))

    def test_secondIdentityWithTheSameNameGetsADerivedName(self, tmp_path, caplog):
        import logging

        from tests.unit.skills.creation_helpers import register_proven_skill

        service = self._service(tmp_path)
        register_proven_skill(service, "synth_first", COLLIDING_NAME, description="第一条")
        with caplog.at_level(logging.WARNING, logger="neurova.skills.skill_service"):
            register_proven_skill(service, "synth_second", COLLIDING_NAME, description="第二条")
        names = dict(service.iter_skills())
        first = str(names["synth_first"]["name"])
        second = str(names["synth_second"]["name"])
        assert second != first, "第二条不同身份的条目仍占用了同一个名字"
        assert "synth_second" in second
        assert callable(claimUniqueName)  # 判据来自同一份实现
        assert any("名字域" in r.message or "同名" in r.message for r in caplog.records), (
            "改名没有出声（静默改名同样不可发现）"
        )

    def test_sameIdentityKeepsItsName(self, tmp_path):
        from tests.unit.skills.creation_helpers import register_proven_skill

        service = self._service(tmp_path)
        register_proven_skill(service, "synth_only", COLLIDING_NAME, description="唯一一条")
        assert dict(service.iter_skills())["synth_only"]["name"] == COLLIDING_NAME
