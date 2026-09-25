"""工单 015 · 经验知识库接口的处置面与真聚合。

两块欠账：

1. `experience_count` 在 `_to_contract` 里被硬编码成 1（`:104`）——同一技能在生产
   库里攒到 7 条，界面上仍然显示 1。展示本身就是假的，处置面建在它上面也没意义；
2. `confidence_score` 为 None 时回落成 `1.0/0.0` 二值，再喂给五格熟练度星级，
   等于把"没有置信度"演成"满级/零级"。读数只该来自真实列（008：`quality_snapshot`
   与 adoption 列），缺就是缺。

处置端点必须与 EKB 的 `operator_disposition` 同一条通路（PUT 之后 GET 得到的
`operator_disposition` 与检索可见性都要跟着变），而不是在响应里编一个态。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from neurova.api.endpoints import experience_knowledge_api as exp_api
from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)

pytestmark = pytest.mark.asyncio

AGENT = "a1"
BASE_INPUT = "搜索 Neurova 相关资料"


@pytest.fixture
def ekb(tmp_path):
    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb-api.db"))


@pytest.fixture(autouse=True)
def _patch_kb(monkeypatch, ekb):
    """端点走单例；不钉住它就会绕过临时库去碰 data/ 下的生产运行数据。"""
    monkeypatch.setattr(exp_api, "get_experience_kb", lambda: ekb)


def _add(ekb, *, tail, skill="web_search", agent=AGENT, confidence=None):
    """默认按"有服务端票据"播种（工单 010 口径）。

    不传 `evidence` ⇒ 落 `unevidenced`，那是形成侧档，本文件测的是契约字段透传，
    别让基准行自带第三态把断言读成两义。
    """
    rid = ekb.add_experience_record(
        skill,
        ExperienceRecord(
            skill_name=skill,
            context={"user_input": f"{BASE_INPUT} {tail}"},
            result={"reply_excerpt": "r"},
            success=True,
        ),
        agent_id=agent,
        confidence_score=confidence,
        evidence=True,
    )
    return rid


def _disposition(value):
    return exp_api.ExperienceDispositionRequest(disposition=value)


class TestExperienceCountIsRealAggregation:
    async def test_ranking_reports_the_skill_row_count(self, ekb):
        """同一 skill 有 N 条 ⇒ 每行显示 N（当前恒 1）。"""
        for i in range(3):
            _add(ekb, tail=f"变体{i}")
        _add(ekb, skill="file_write", tail="写一份报告")

        listing = await exp_api.get_experience_ranking(agent_id=AGENT, page=1, size=20, task_type=None)
        by_skill = {i["skill_name"]: i["experience_count"] for i in listing["data"]["items"]}
        assert by_skill == {"web_search": 3, "file_write": 1}

    async def test_count_is_scoped_to_the_agent(self, ekb):
        """聚合口径与列表口径必须同源：a1 的 3 条不能算到 a2 头上。"""
        for i in range(3):
            _add(ekb, tail=f"变体{i}")
        _add(ekb, agent="a2", tail="别人的")

        a1 = await exp_api.get_experience_ranking(agent_id=AGENT, page=1, size=20, task_type=None)
        assert {i["experience_count"] for i in a1["data"]["items"]} == {3}
        a2 = await exp_api.get_experience_ranking(agent_id="a2", page=1, size=20, task_type=None)
        assert {i["experience_count"] for i in a2["data"]["items"]} == {1}

    async def test_single_record_shares_the_same_count(self, ekb):
        rid = _add(ekb, tail="唯一")
        _add(ekb, tail="另外的")
        _add(ekb, tail="再一个")
        one = await exp_api.get_experience(record_id=str(rid))
        assert one["data"]["experience_count"] == 3


class TestConfidenceIsNotFakedFromBinary:
    async def test_missing_confidence_surfaces_as_none_not_a_full_rating(self, ekb):
        """None 置信度不得被兜成 1.0 —— 那是把"没测到"演成"满分"。"""
        rid = _add(ekb, tail="缺置信", confidence=None)
        data = (await exp_api.get_experience(record_id=str(rid)))["data"]
        assert data["success_rate"] is None
        assert data["proficiency"] is None

    async def test_real_confidence_still_passes_through(self, ekb):
        """反向锁：有值时照常给数，不得为了"看着像缺数据"一律抹成 None。"""
        rid = _add(ekb, tail="有置信", confidence=0.72)
        data = (await exp_api.get_experience(record_id=str(rid)))["data"]
        assert data["success_rate"] == pytest.approx(0.72)
        assert data["proficiency"] == pytest.approx(0.72)


class TestDispositionEndpoint:
    async def test_put_writes_through_to_the_row(self, ekb):
        rid = _add(ekb, tail="甲")
        resp = await exp_api.set_experience_disposition(
            record_id=str(rid), body=_disposition("demoted")
        )
        assert resp["code"] == 0
        assert resp["data"]["operator_disposition"] == "demoted"
        assert ekb.get_record_by_id(rid)["operator_disposition"] == "demoted"

    async def test_endorsed_state_is_readable_back_from_the_api(self, ekb):
        """审核态同样要落到行上（它是"看过"的登记，不是删除的前戏）。"""
        rid = _add(ekb, tail="乙")
        await exp_api.set_experience_disposition(record_id=str(rid), body=_disposition("endorsed"))
        assert ekb.get_record_by_id(rid)["operator_disposition"] == "endorsed"
        data = (await exp_api.get_experience(record_id=str(rid)))["data"]
        assert data["operator_disposition"] == "endorsed"

    async def test_restore_is_expressed_as_null_not_a_magic_string(self, ekb):
        rid = _add(ekb, tail="丙")
        await exp_api.set_experience_disposition(record_id=str(rid), body=_disposition("suppressed"))
        await exp_api.set_experience_disposition(record_id=str(rid), body=_disposition(None))
        assert ekb.get_record_by_id(rid)["operator_disposition"] is None
        data = (await exp_api.get_experience(record_id=str(rid)))["data"]
        assert data["operator_disposition"] is None

    async def test_suppressed_record_is_invisible_to_similarity_search(self, ekb):
        """处置与检索必须同一条链：PUT 之后 /similar 里查不到它，但 /{id} 仍在。"""
        hidden = _add(ekb, tail="丁")
        kept = _add(ekb, tail="戊")
        await exp_api.set_experience_disposition(
            record_id=str(hidden), body=_disposition("suppressed")
        )

        similar = await exp_api.find_similar_experiences(
            exp_api.FindSimilarExperiencesRequest(
                agent_id=AGENT, query=f"{BASE_INPUT} 丁", limit=5
            )
        )
        assert [r["id"] for r in similar["data"]["results"]] == [str(kept)]
        assert (await exp_api.get_experience(record_id=str(hidden)))["code"] == 0

    async def test_unknown_disposition_is_a_validation_error(self, ekb):
        rid = _add(ekb, tail="己")
        with pytest.raises(ValidationError):
            _disposition("bananas")
        assert ekb.get_record_by_id(rid)["operator_disposition"] is None

    async def test_missing_record_returns_404(self, ekb):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await exp_api.set_experience_disposition(record_id="424242", body=_disposition("demoted"))
        assert exc.value.status_code == 404

    async def test_disposition_never_deletes_the_record(self, ekb):
        """处置面与删除是两件事：走完全部处置态后行数不变。"""
        rid = _add(ekb, tail="庚")
        for state in ("demoted", "suppressed", "endorsed", None):
            await exp_api.set_experience_disposition(record_id=str(rid), body=_disposition(state))
        assert len(ekb.get_experience_records(agent_id=AGENT)) == 1


class TestContractCarriesTheEvidenceColumns:
    async def test_record_exposes_adoption_and_disposition(self, ekb):
        """运营页要能按新列重建视图（008 口径），所以契约里必须带得上。"""
        rid = _add(ekb, tail="辛")
        ekb.record_injection_adoption([rid], False)
        item = (await exp_api.get_experience(record_id=str(rid)))["data"]
        assert item["adoption_outcome"] == "failure"
        assert item["evidence_state"] == "evidenced"
        assert item["injected_count"] == 1
        assert item["seen_count"] == 1
        assert item["operator_disposition"] is None
