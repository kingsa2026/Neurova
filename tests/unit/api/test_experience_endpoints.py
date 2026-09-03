"""
Experience Knowledge API 真实数据测试（防回归）

背景：experience_knowledge_api.py 曾为内存 stub（进程级 _RECORDS 空 dict，
无写入方、无持久化、与真实 ExperienceKnowledgeBase/结晶系统脱节）——
前端页面恒空数据。修复：端点桥接 SQLite 持久化的 ExperienceKnowledgeBase，
契约对齐前端 experience.ts（agent_id 过滤、分页 {items,total}、字段映射
outcome/proficiency/success_rate 等）。
"""

import pytest

from neurova.api.endpoints import experience_knowledge_api as exp_api
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase


@pytest.fixture
def ekb(tmp_path):
    """隔离的临时库实例（不碰 data/experience_knowledge.db 真库）。"""
    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb-test.db"))


@pytest.fixture(autouse=True)
def _patch_kb(monkeypatch, ekb):
    monkeypatch.setattr(exp_api, "get_experience_kb", lambda: ekb)


def _sample_payload(agent="a1", task="web_search", outcome="success"):
    return {
        "agent_id": agent,
        "task_type": task,
        "context": "搜索 Neurova 相关资料",
        "outcome": outcome,
        "lessons": ["用英文查询命中率更高"],
        "metadata": {"source": "unit-test"},
    }


def _req(**kw):
    """构造 pydantic AddExperienceRecordRequest（端点直接调用需显式模型）。"""
    return exp_api.AddExperienceRecordRequest.model_validate(_sample_payload(**kw))


class TestExperienceRecordsReal:
    """/records POST + /ranking GET 必须落真实库并返回分页契约。"""

    @pytest.mark.asyncio
    async def test_create_and_list_contract(self):
        res = await exp_api.add_experience_record(_req())

        assert res["code"] == 0
        record = res["data"]
        assert record["id"]
        assert record["task_type"] == "web_search"
        assert record["outcome"] == "success"
        assert record["agent_id"] == "a1"

        listing = await exp_api.get_experience_ranking(agent_id="a1", page=1, size=20, task_type=None)
        data = listing["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["context"].startswith("搜索 Neurova")
        assert item["skill_name"] == "web_search"
        assert item["success_rate"] is not None
        assert item["proficiency"] is not None
        assert item["lessons"] == ["用英文查询命中率更高"]

    @pytest.mark.asyncio
    async def test_agent_scope_isolation(self):
        await exp_api.add_experience_record(_req(agent="a1"))
        await exp_api.add_experience_record(_req(agent="a2", task="code", outcome="failure"))

        a1 = await exp_api.get_experience_ranking(agent_id="a1", page=1, size=20, task_type=None)
        a2 = await exp_api.get_experience_ranking(agent_id="a2", page=1, size=20, task_type=None)
        assert a1["data"]["total"] == 1
        assert a2["data"]["total"] == 1
        assert a1["data"]["items"][0]["skill_name"] == "web_search"
        assert a2["data"]["items"][0]["skill_name"] == "code"

    @pytest.mark.asyncio
    async def test_pagination(self):
        for i in range(5):
            await exp_api.add_experience_record(_req(agent="a1", task=f"task{i}"))
        listing = await exp_api.get_experience_ranking(agent_id="a1", page=1, size=2, task_type=None)
        assert listing["data"]["total"] == 5
        assert len(listing["data"]["items"]) == 2


class TestExperienceStatsReal:
    """/stats 必须返回前端 ExperienceStats 契约。"""

    @pytest.mark.asyncio
    async def test_stats_contract(self):
        await exp_api.add_experience_record(_req(agent="a1", outcome="success"))
        await exp_api.add_experience_record(_req(agent="a1", outcome="failure"))

        res = await exp_api.get_experience_stats(agent_id="a1")
        data = res["data"]
        assert data["total_experiences"] == 2
        assert 0 < data["success_rate"] < 1
        assert isinstance(data["top_categories"], list)
        assert any(c["category"] == "web_search" for c in data["top_categories"])


class TestExperienceDeleteReal:
    """/{id} 删除必须真实生效。"""

    @pytest.mark.asyncio
    async def test_delete_record(self):
        created = await exp_api.add_experience_record(_req())
        rid = created["data"]["id"]

        res = await exp_api.delete_experience(rid)
        assert res["code"] == 0

        listing = await exp_api.get_experience_ranking(agent_id="a1", page=1, size=20, task_type=None)
        assert listing["data"]["total"] == 0
