# -*- coding: utf-8 -*-
"""四动词门面的租户隔离（§8 第 9 条点名「统一分页/投影/**租户隔离**」，S5 门点名本档）。

门面本身是纯转发（`knowledge_access_facade` 零业务逻辑），所以这一格判的不是门面代码，
而是**转发之后可见域有没有跟着登录者走**：query 动词带 `asOf/knownAt` 时落到事实层
`factsBitemporal(agentId, tenantId=…)`，tenantId 必须取自登录者而不是请求体。

两件事分开钉：
1. 跨租户不可见（A 看不到 B 的事实，反之亦然）——空集即红，所以本档必须先自证
   「两侧各有一行可查」，否则判据会在空库上空转成绿。
2. 门面路径与直连 `/search` 的可见域一致（同一个 current_user 两处读数相同），
   否则"统一门面"就变成了第二条取数口径。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

TENANT_A = {"user_id": "1", "username": "a", "role": "admin", "tenant_id": "tenantA"}
TENANT_B = {"user_id": "2", "username": "b", "role": "admin", "tenant_id": "tenantB"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    yield s
    s.close()


@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_access_facade, knowledge_core

    app = FastAPI()
    app.include_router(knowledge_access_facade.router, prefix=PREFIX)
    app.include_router(knowledge_core.router, prefix=PREFIX)
    app.state_identity = dict(TENANT_A)   # 由用例改写
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(app.state_identity)
    return TestClient(app)


def _admitFact(store, tenantId, subject):
    content = "%s is_a Order" % subject
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", tenantId=tenantId, subjectLabel=subject,
        predicateTermId="is_a", objectTerm="Order", content=content,
        validFrom="2026-01-01", validUntil="2026-12-31",
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:%s" % tenantId, "statementText": content}],
    )).factId


def _queryKeys(client, query):
    """取回可见域的**主体键**：事实视图的 title 是 `subject_key · 客体`，标签不在载荷里，
    所以判可见性只能按键比，不能按人类可读名比（按名比会把"取错字段"误判成"隔离破了"）。
    """
    resp = client.post(PREFIX + "/access/query", params={"agent_id": "default"},
                       json={"query": query, "asOf": "2026-06-01",
                             "knownAt": "2026-12-31"})
    assert resp.status_code == 200, resp.text
    return {str((item.get("metadata") or {}).get("subject_key") or "")
            for item in resp.json()}


class TestFacadeTenantIsolation:
    def testEachTenantSeesOnlyItsOwnFacts(self, client, store):
        _admitFact(store, "tenantA", "甲租户订单")
        _admitFact(store, "tenantB", "乙租户订单")
        keyA = store.resolveSubjectKey("default", "甲租户订单", tenantId="tenantA")
        keyB = store.resolveSubjectKey("default", "乙租户订单", tenantId="tenantB")
        assert keyA and keyB and keyA != keyB, (keyA, keyB)

        client.app.state_identity = dict(TENANT_A)
        keysA = _queryKeys(client, "订单")
        client.app.state_identity = dict(TENANT_B)
        keysB = _queryKeys(client, "订单")

        # 先自证两侧都真取到了自己的行——否则下面的"互不可见"是空集套空集，什么都没判
        assert keysA == {keyA}, (keysA, keyA)
        assert keysB == {keyB}, (keysB, keyB)

    def testFacadeMatchesDirectSearchVisibility(self, client, store):
        """门面与直连 `/search` 同一可见域：出现第二条取数口径即为双源。"""
        _admitFact(store, "tenantA", "甲租户订单")
        _admitFact(store, "tenantB", "乙租户订单")
        client.app.state_identity = dict(TENANT_A)
        body = {"query": "订单", "asOf": "2026-06-01", "knownAt": "2026-12-31"}

        viaFacade = _queryKeys(client, "订单")
        resp = client.post(PREFIX + "/search", params={"agent_id": "default"}, json=body)
        assert resp.status_code == 200, resp.text
        direct = {str((item.get("metadata") or {}).get("subject_key") or "")
                  for item in resp.json()}

        assert viaFacade == direct, (
            "同一登录者在门面与直连两条路径上读数不一致——可见域长了第二张嘴")
        assert viaFacade, "两条路径都查不到行，本档退化成空判据"
