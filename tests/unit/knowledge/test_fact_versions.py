# -*- coding: utf-8 -*-
"""事实版本历史与回滚（v19）——每次生命周期变更都要留得下、回得去。"""
from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import (
    KnowledgeFactStore,
    get_knowledge_fact_store,
    reset_knowledge_fact_store,
)


@pytest.fixture(autouse=True)
def _resetSingleton():
    reset_knowledge_fact_store()
    yield
    reset_knowledge_fact_store()


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _fact(store, content="预算金额 100 万元", objectTerm="100万元", subject="Alpha",
          tenantId="default"):
    return store.upsertFact(
        agentId="agent-a",
        subjectKey=subject,
        predicateTermId="pred.budget",
        objectTerm=objectTerm,
        content=content,
        contentKey="ck:%s:%s" % (subject, objectTerm),
        tenantId=tenantId,
    )


class TestVersionHistory:
    def test_schemaIsV19(self, store):
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version >= 20
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "knowledge_fact_versions" in tables
        assert "knowledge_baselines" in tables

    def test_createWritesFirstVersion(self, store):
        factId = _fact(store)

        versions = store.history(factId)

        assert len(versions) == 1
        assert versions[0]["change_type"] == "create"
        assert versions[0]["snapshot"]["fact_id"] == factId
        assert versions[0]["snapshot"]["status"] == "active"

    def test_retractThenRollbackRestoresStatusAndContent(self, store):
        factId = _fact(store)
        store.retract(factId, reason="来源被撤回")

        afterRetract = store.history(factId)
        assert [v["change_type"] for v in afterRetract[:2]] == ["retract", "create"]
        assert store.fact(factId)["status"] == "retracted"

        restored = store.rollback(
            factId, 1, operator="admin", reason="来源恢复，按 v1 回滚"
        )

        assert restored["status"] == "active"
        assert restored["content"] == "预算金额 100 万元"
        assert restored["retracted_at"] is None
        latest = store.history(factId)[0]
        assert latest["change_type"] == "rollback"
        assert latest["operator"] == "admin"
        assert latest["reason"] == "来源恢复，按 v1 回滚"

    def test_rollbackRequiresOperatorAndReason(self, store):
        factId = _fact(store)

        with pytest.raises(ValueError, match="操作人与依据"):
            store.rollback(factId, 1, operator="", reason="理由")

        with pytest.raises(ValueError, match="操作人与依据"):
            store.rollback(factId, 1, operator="admin", reason="  ")

    def test_rollbackUnknownVersionIs404Like(self, store):
        factId = _fact(store)

        with pytest.raises(LookupError):
            store.rollback(factId, 99, operator="admin", reason="不存在的版本")

    def test_supersedeAndExpireLeaveVersions(self, store):
        oldId = _fact(store)
        newId = store.upsertFact(
            agentId="agent-a",
            subjectKey="Alpha",
            predicateTermId="pred.budget",
            objectTerm="120万元",
            content="预算金额 120 万元",
            contentKey="ck:Alpha:120万元",
        )
        store.supersede(newId, oldId, reason="新预算")
        assert store.history(oldId)[0]["change_type"] == "supersede"
        assert store.history(oldId)[0]["snapshot"]["status"] == "superseded"

        expiring = _fact(store, content="临时口径 5%", objectTerm="5%", subject="Beta")
        store.setValidUntil(expiring, "2020-01-01T00:00:00+00:00")
        store.expireDueFacts(now="2026-01-01T00:00:00+00:00")

        assert store.history(expiring)[0]["change_type"] == "expire"
        assert store.fact(expiring)["status"] == "expired"

    def test_reviveLeavesVersion(self, store):
        factId = _fact(store)
        store.retract(factId, reason="误撤")

        assert store.reviveRetracted(factId, reason="重新主张") is True

        assert store.history(factId)[0]["change_type"] == "revive"


class TestBaselines:
    def testBaselineKeepsOnlyFactRefs(self, store):
        first = _fact(store)
        second = _fact(store, content="缓存策略 5 分钟", objectTerm="5分钟", subject="Gamma")

        created = store.createBaseline(
            scope="agent", scopeKey="agent-a", createdBy="admin", reason="上线前冻结"
        )

        assert created["fact_count"] == 2
        baseline = store.baseline(created["baseline_id"])
        assert baseline["snapshot"]["fact_ids"] == sorted([first, second])
        assert "content" not in baseline["snapshot"]
        assert store.listBaselines(scope="agent")[0]["baseline_id"] == created["baseline_id"]
        assert store.listBaselines(scope="global") == []

    def testExplicitFactIdsTakePrecedence(self, store):
        first = _fact(store)
        _fact(store, content="缓存策略 5 分钟", objectTerm="5分钟", subject="Gamma")

        created = store.createBaseline(factIds=[first], createdBy="admin")

        assert store.baseline(created["baseline_id"])["snapshot"]["fact_ids"] == [first]

    def testSingletonFactorySharesHistory(self, tmp_path, monkeypatch):
        path = str(tmp_path / "singleton.db")
        monkeypatch.setattr(
            "neurova.knowledge.foundation.knowledge_facts.DEFAULT_FACT_DB", path
        )
        store = get_knowledge_fact_store(path)
        factId = _fact(store)

        assert get_knowledge_fact_store(path) is store
        assert get_knowledge_fact_store(path).history(factId)[0]["change_type"] == "create"


class TestBaselineTenantBoundary:
    def testRejectsForeignTenantFactRefs(self, store):
        tenantFact = store.upsertFact(
            "agent-a", "Alpha", "pred.budget", "100万元", "预算 100 万元",
            contentKey="ck:tenant", tenantId="t1",
        )

        with pytest.raises(ValueError, match="其他租户"):
            store.createBaseline(factIds=[tenantFact], tenantId="t2")

    def testAutomaticScopeOnlyFreezesOwnTenant(self, store):
        _fact(store, content="租户一事实", objectTerm="1", subject="A1", tenantId="t1")
        store.upsertFact("agent-a", "A2", "pred.budget", "2", "租户二事实",
                         contentKey="ck:a2", tenantId="t2")

        created = store.createBaseline(tenantId="t1", createdBy="admin")

        assert created["fact_count"] == 1
        assert len(store.baseline(created["baseline_id"])["snapshot"]["fact_ids"]) == 1


class TestBaselineTimeWindow:
    def testOnlyFactsInsideWindowAreFrozen(self, store):
        older = store.upsertFact(
            "agent-a", "A", "pred.budget", "1", "older",
            contentKey="ck:older", recordedAt="2026-01-01T00:00:00+00:00",
        )
        newer = store.upsertFact(
            "agent-a", "A", "pred.budget", "2", "newer",
            contentKey="ck:newer", recordedAt="2026-06-01T00:00:00+00:00",
        )

        created = store.createBaseline(
            tenantId="default", createdBy="admin",
            timeFrom="2026-03-01T00:00:00+00:00",
            timeTo="2026-12-31T00:00:00+00:00",
        )

        ids = store.baseline(created["baseline_id"])["snapshot"]["fact_ids"]
        assert ids == [newer]
        assert older not in ids
