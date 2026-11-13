# -*- coding: utf-8 -*-
"""C2：POST /v1/knowledge/conflicts/{id}/llm-advice 端点契约。

仅管理员；只对 pending 事实轴冲突给意见；LLM 坏输出 502、不可用 503；
不落账不改状态（意见后冲突仍 pending，resolve 通道不受影响）。
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.api.deps import get_llm_client
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}

PREFIX = "/v1/knowledge"


def _seedPendingConflict(store: KnowledgeFactStore) -> str:
    """两条不同谓词事实（互不顶掉）＋手工 pending 冲突行，成员可控。"""
    gate = productionAdmissionGate(store)
    for obj, pred in (("在线", "status_a"), ("离线", "status_b")):
        content = "A1 %s %s" % (pred, obj)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="A1", predicateTermId=pred,
            objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
    rows = store._conn.execute(
        "SELECT fact_id FROM knowledge_facts ORDER BY fact_id").fetchall()
    memberIds = [str(r["fact_id"]) for r in rows][:2]
    conflictId = store.insertConflict(
        kind="value", subjectKey="s_a1", predicateTermId="status_a",
        memberFactIds=memberIds, severity=0.6,
        recommendedPolicy="manual", policyBasis="三项均无差异",
        status="pending", winnerFactId=None, tenantId="default")
    assert conflictId, "pending 冲突行必须落账"
    return conflictId


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "kb.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda *a, **k: store)
    conflictId = _seedPendingConflict(store)

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
        lambda: holder["user"])
    fake_llm = type("FakeLlm", (), {
        "chat": staticmethod(lambda messages, **kw: type(
            "R", (), {"content": json.dumps({
                "contradicts": True, "winner_fact_id": "f?",
                "reason": "测试意见"})})()),
    })()

    def _fake_chat(messages, **kwargs):
        memberLine = [ln for ln in messages[1]["content"].splitlines()
                      if "fact_id=" in ln]
        winner = memberLine[0].split("fact_id=")[1].split(" ")[0]
        return type("R", (), {"content": json.dumps({
            "contradicts": True, "winner_fact_id": winner,
            "reason": "第一条更可信"})})()

    fake_llm.chat = _fake_chat
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    client = TestClient(app)
    yield client, holder, store, conflictId
    store.close()


class TestLlmAdviceApi:
    def test_admin_only(self, api):
        client, holder, store, conflictId = api
        holder["user"] = dict(ALICE)
        assert client.post(f"{PREFIX}/conflicts/{conflictId}/llm-advice").status_code == 403

    def test_returnsAdviceForPendingConflict(self, api):
        client, holder, store, conflictId = api
        resp = client.post(f"{PREFIX}/conflicts/{conflictId}/llm-advice")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["contradicts"] is True
        assert data["winner_fact_id"] in data["members"]
        assert data["reason"] == "第一条更可信"
        # 意见不改状态：冲突仍 pending，可继续走 resolve
        pending = store.conflicts(status="pending", tenantId="default")
        assert any(str(r["conflict_id"]) == conflictId for r in pending)

    def test_unknownOrResolvedConflictIs404(self, api):
        client, holder, store, conflictId = api
        assert client.post(f"{PREFIX}/conflicts/nope/llm-advice").status_code == 404

    def test_badLlmOutputIs502(self, api, monkeypatch):
        client, holder, store, conflictId = api

        def _bad_chat(messages, **kwargs):
            return type("R", (), {"content": "说不清"})()

        app = client.app
        app.dependency_overrides[get_llm_client] = lambda: type(
            "BadLlm", (), {"chat": staticmethod(_bad_chat)})()
        resp = client.post(f"{PREFIX}/conflicts/{conflictId}/llm-advice")
        assert resp.status_code == 502

    def test_llmOutageIs503(self, api):
        client, holder, store, conflictId = api

        def _down_chat(messages, **kwargs):
            raise ConnectionError("网关不可达")

        client.app.dependency_overrides[get_llm_client] = lambda: type(
            "DownLlm", (), {"chat": staticmethod(_down_chat)})()
        resp = client.post(f"{PREFIX}/conflicts/{conflictId}/llm-advice")
        assert resp.status_code == 503
