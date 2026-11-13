# -*- coding: utf-8 -*-
"""知识条目 revision 回滚端点：POST /knowledge/{id}/revisions/{index}/rollback。

- index 按 list_revisions 序（0=最新）；
- 回滚撤销该次变更（账本 old 值写回 changed_fields），回滚本身也进账本
  （reason=rollback，记录回滚前现值）——回滚可再回滚；
- 回滚保留回滚前最新版完整快照（/versions 版本链）；
- Ontology 感知：回滚落知识活动台账（knowledge_revision_rollback）；
- 属主/管理员可操作，他人 403；非法序号 404。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api import deps as knowledge_deps
from neurova.knowledge.repository import KnowledgeRepository

OWNER = {"user_id": "9", "username": "owner", "role": "user", "tenant_id": "default"}
OTHER = {"user_id": "7", "username": "other", "role": "user", "tenant_id": "default"}
PREFIX = "/api/v1/knowledge"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr(
        "neurova.knowledge.repository.get_knowledge_repository", lambda: r)
    return r


@pytest.fixture
def fact_store(tmp_path, monkeypatch):
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    yield s
    s.close()


@pytest.fixture
def client(repo, fact_store):
    from neurova.api.endpoints import knowledge_core

    app = FastAPI()
    app.include_router(knowledge_core.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(OWNER)
    app.dependency_overrides[
        knowledge_deps.strictIdentityGate] = lambda: dict(OWNER)
    return TestClient(app)


def _seedEntry(repo, title="v1"):
    item = repo.create_knowledge(
        agent_id="default", title=title, content="内容 " + title,
        category="general", tags=[], source="entry", confidence=0.9,
        visibility="private", owner_user_id=OWNER["user_id"],
        tenant_id="default", dedupe=False)
    return item


class TestRevisionRollback:
    def test_rollbackRestoresPreviousValues(self, client, repo):
        entry = _seedEntry(repo, "v1")
        kid = entry["knowledge_id"]
        assert repo.update_knowledge("default", kid, {"title": "v2"}) is True
        r = client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        assert r.status_code == 200, r.text[:200]
        assert r.json()["title"] == "v1", "回滚应恢复旧标题"
        # 回滚本身进账本（可再回滚）
        revs = client.get(f"{PREFIX}/{kid}/revisions").json()
        assert revs[0].get("reason") == "rollback"
        assert revs[0]["old"]["title"] == "v2"

    def test_rollbackKeepsPreRollbackSnapshot(self, client, repo):
        """回滚后：回滚前最新版完整快照入版本链（/versions 可读）。"""
        entry = _seedEntry(repo, "v1")
        kid = entry["knowledge_id"]
        repo.update_knowledge("default", kid, {"title": "v2", "content": "v2 内容"})
        r = client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        assert r.status_code == 200
        versions = client.get(f"{PREFIX}/{kid}/versions").json()["data"]
        assert len(versions) >= 2, "编辑与回滚都应留完整快照"
        rollbackSnap = versions[0]
        assert rollbackSnap["reason"] == "rollback"
        assert rollbackSnap["data"]["title"] == "v2", "回滚前最新版（v2）应被保留"
        assert rollbackSnap["data"]["content"] == "v2 内容"

    def test_rollbackLandsOntologyActivity(self, client, repo, fact_store):
        """Ontology 感知：回滚落知识活动台账（kind=knowledge_revision_rollback）。"""
        entry = _seedEntry(repo, "v1")
        kid = entry["knowledge_id"]
        repo.update_knowledge("default", kid, {"title": "v2"})
        r = client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        assert r.status_code == 200
        rows = fact_store._conn.execute(
            "SELECT activity_kind, inputs_json FROM knowledge_activities"
            " WHERE activity_kind = 'knowledge_revision_rollback'").fetchall()
        assert len(rows) >= 1, "回滚应在知识活动台账留痕（Ontology 感知）"
        assert "knowledge_id" in rows[0]["inputs_json"]

    def test_rollbackIsReversible(self, client, repo):
        entry = _seedEntry(repo, "v1")
        kid = entry["knowledge_id"]
        repo.update_knowledge("default", kid, {"title": "v2"})
        client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        # 再回滚一次（撤销回滚）→ 标题回到 v2
        r = client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        assert r.status_code == 200
        assert r.json()["title"] == "v2"

    def test_badIndex404(self, client, repo):
        entry = _seedEntry(repo, "v1")
        kid = entry["knowledge_id"]
        r = client.post(f"{PREFIX}/{kid}/revisions/99/rollback")
        assert r.status_code == 404

    def test_otherUser403(self, client, repo):
        # 公开条目：他人可见不可改（私有条目对他人是 404 不泄露存在性）
        entry = repo.create_knowledge(
            agent_id="default", title="pub-v1", content="内容 pub-v1",
            category="general", tags=[], source="entry", confidence=0.9,
            visibility="public", owner_user_id=OWNER["user_id"],
            tenant_id="default", dedupe=False)
        kid = entry["knowledge_id"]
        repo.update_knowledge("default", kid, {"title": "v2"})
        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(OTHER)
        client.app.dependency_overrides[
            knowledge_deps.strictIdentityGate] = lambda: dict(OTHER)
        r = client.post(f"{PREFIX}/{kid}/revisions/0/rollback")
        assert r.status_code == 403
