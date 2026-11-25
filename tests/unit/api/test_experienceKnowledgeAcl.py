# -*- coding: utf-8 -*-
"""PLUG-06 红灯：经验知识库端点仅登录门、无 ACL，跨 Agent 越权。

审计（2026-11-25 全仓审计 · PLUG-06）：experience_knowledge_api 全部端点只
要求登录；自动写入（post_chat_pipeline 反思沉淀）把 user_input/reply_excerpt
写进记录——任何登录用户可读取/处置/删除他人 Agent 的经验，等于暴露他人会话
片段。

判据（ACL 与自动写入 scope 一致）：经验记录归 agent，访问权即 agent 访问权
——判据转交全仓单源 agent_access（admin 全量；非 admin 仅属主；无主仅 admin）。
记录 id 寻址面防 IDOR：非属主与不存在同形 404。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import experience_knowledge_api as exp_api
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase, ExperienceRecord

ALICE = {"user_id": "alice", "username": "alice", "role": "user"}
BOB = {"user_id": "bob", "username": "bob", "role": "user"}
ADMIN = {"user_id": "9", "username": "root", "role": "admin"}

AGENT_A = "a1"  # alice 的 agent
AGENT_B = "a2"  # bob 的 agent


@pytest.fixture
def ekb(tmp_path):
    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb-acl.db"))


@pytest.fixture(autouse=True)
def _patch_kb(monkeypatch, ekb):
    monkeypatch.setattr(exp_api, "get_experience_kb", lambda: ekb)


@pytest.fixture
def agentOwners(monkeypatch):
    """把 agent 属主解析钉到测试名册（验 ACL 接线，不验查库链）。"""
    import neurova.api.agent_access as access_mod

    owners = {AGENT_A: "alice", AGENT_B: "bob"}
    monkeypatch.setattr(access_mod, "agentOwnerById", lambda agent_id: owners.get(str(agent_id or "")))
    return owners


@pytest.fixture
def client():
    app = FastAPI()
    # 生产挂载：注册表前缀 /v1/experience（无模块自述前缀），叠加 /api/v1 层
    app.include_router(exp_api.router, prefix="/api/v1/experience")
    tc = TestClient(app)

    def asUser(identity):
        tc.app.dependency_overrides[auth_mod.get_current_user] = lambda: identity

    tc.as_user = asUser
    return tc


@pytest.fixture
def seededRecord(ekb):
    """alice 的 agent a1 名下一条真实经验（含会话片段）。"""
    rid = ekb.add_experience_record(
        "web_search",
        ExperienceRecord(
            skill_name="web_search",
            context={"user_input": "alice 的私密问题", "task_type": "web_search"},
            result={"reply_excerpt": "alice 的私密回复片段"},
            success=True,
            feedback="alice 的私密问题",
        ),
        agent_id=AGENT_A,
    )
    return rid


BASE = "/api/v1/experience"


class TestAgentScopedEndpoints:
    def test_nonOwnerCannotReadOthersRanking(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.get(f"{BASE}/ranking", params={"agent_id": AGENT_A})
        assert resp.status_code == 403, (
            f"非属主读取他人 agent 经验列表未被拒：{resp.status_code} {resp.text[:160]}"
        )

    def test_nonOwnerCannotReadOthersStats(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.get(f"{BASE}/stats", params={"agent_id": AGENT_A})
        assert resp.status_code == 403, f"非属主读他人 agent 统计未被拒：{resp.status_code}"

    def test_nonOwnerCannotSearchOthersExperiences(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.post(f"{BASE}/similar", json={"agent_id": AGENT_A, "query": "私密", "limit": 5})
        assert resp.status_code == 403, f"非属主检索他人 agent 经验未被拒：{resp.status_code}"

    def test_nonOwnerCannotWriteIntoOthersAgent(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.post(f"{BASE}/records", json={
            "agent_id": AGENT_A, "task_type": "web_search",
            "context": "越权写入", "outcome": "success",
        })
        assert resp.status_code == 403, (
            f"非属主向他人 agent 写入经验未被拒：{resp.status_code} {resp.text[:160]}"
        )

    def test_nonOwnerEmptyAgentIdIs403(self, client, agentOwners, seededRecord):
        """空 agent_id = 全库扫读，非 admin 一律拒绝。"""
        client.as_user(BOB)
        resp = client.get(f"{BASE}/ranking")
        assert resp.status_code == 403, f"非 admin 空 agent_id 全库读未被拒：{resp.status_code}"

    def test_ownerAndAdminKeepAccess(self, client, agentOwners, seededRecord):
        """收紧不得把属主/管理员挡在门外。"""
        client.as_user(ALICE)
        assert client.get(f"{BASE}/ranking", params={"agent_id": AGENT_A}).status_code == 200
        assert client.get(f"{BASE}/stats", params={"agent_id": AGENT_A}).status_code == 200

        client.as_user(ADMIN)
        assert client.get(f"{BASE}/ranking", params={"agent_id": AGENT_A}).status_code == 200

    def test_ownerWritesToOwnAgent(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.post(f"{BASE}/records", json={
            "agent_id": AGENT_B, "task_type": "code", "context": "自己 agent 写入", "outcome": "success",
        })
        assert resp.status_code == 200, f"属主写自己 agent 被误拒：{resp.status_code} {resp.text[:160]}"


class TestRecordAddressedEndpoints:
    def test_nonOwnerCannotReadRecord(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.get(f"{BASE}/{seededRecord}")
        assert resp.status_code == 404, (
            f"非属主读他人经验记录未被拒（应与不存在同形 404）：{resp.status_code} {resp.text[:160]}"
        )

    def test_nonOwnerCannotDisposeRecord(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.put(f"{BASE}/{seededRecord}/disposition", json={"disposition": "demoted"})
        assert resp.status_code == 404, f"非属主处置他人经验未被拒：{resp.status_code}"

    def test_nonOwnerCannotDeleteRecord(self, client, agentOwners, seededRecord):
        client.as_user(BOB)
        resp = client.delete(f"{BASE}/{seededRecord}")
        assert resp.status_code == 404, f"非属主删除他人经验未被拒：{resp.status_code}"

    def test_ownerAndAdminManageOwnRecords(self, client, agentOwners, seededRecord, ekb):
        client.as_user(ALICE)
        resp = client.put(f"{BASE}/{seededRecord}/disposition", json={"disposition": "endorsed"})
        assert resp.status_code == 200, f"属主处置自己经验被误拒：{resp.status_code} {resp.text[:160]}"
        assert client.get(f"{BASE}/{seededRecord}").status_code == 200

        client.as_user(ADMIN)
        assert client.delete(f"{BASE}/{seededRecord}").status_code == 200
