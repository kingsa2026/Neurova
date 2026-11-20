# -*- coding: utf-8 -*-
"""P1-3 企业源摄取「启动钩子 + 24h 巡检补跑」双保险（2026-11-21 拍板 D-E）。

- auditEnterpriseSyncStaleness(triggerKind)：遍历 listSyncTenants() 每租户每启用源，
  查 enterprise_sync_history 最近一条成功记录；距今超过
  NEUROVA_ENTERPRISE_SYNC_STALE_HOURS（默认 24，env 可配）或从未成功 →
  runOnceAsync(tenant, source, triggerKind) 补跑；单源异常不阻断其余（fail-soft），
  返回 {checked, triggered, skipped, failed} 汇总。
- 周期巡检经既有调度器 addSystemJob（jobId=enterprise-sync-staleness-audit，
  seconds=86400），重复注册幂等（replace_existing 语义）。
- 告警面：本批只进 admin 同步历史读面（trigger_kind TEXT 列，新取值免迁移）。
"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.enterprise.protocols import ChangeBatch
from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    _recordSyncHistory,
    auditEnterpriseSyncStaleness,
    getSourceRegistry,
    registerEnterpriseSyncAuditJob,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


class StubAdapter:
    """可控适配器：boom=True 时 fetchBatch 抛错（单源故障注入）。"""

    def __init__(self, boom: bool = False):
        self._boom = boom

    async def fetchBatch(self, cursor, limit):
        if self._boom:
            raise RuntimeError("source exploded")
        return ChangeBatch(rows=[], nextCursor=None, hasMore=False)

    async def health(self):
        from neurova.knowledge.enterprise.protocols import SourceHealth

        return SourceHealth(status="ok", reason="")


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _saveSource(store, sourceId, tenant="default", enabled=True,
                intervalSeconds=300, boom=False):
    """造一个启用源（sql 描述符 + interval），并把 stub 适配器挂进进程注册表。"""
    ingestor = EnterpriseIngestor(store)
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    OntologyTermRegistry(store).register("row", "relation")
    descriptor = {"sourceType": "sql", "sourceId": sourceId, "dialect": "sqlite",
                  "database": "legacy.db", "cursorColumn": "id", "columns": ["id"],
                  "subject": {"column": "id"}, "predicate": {"termId": "row"},
                  "object": {"column": "id", "kind": "column"}}
    ingestor.saveConfig(tenant, sourceId, descriptor, enabled=enabled)
    if intervalSeconds:
        ingestor.setSyncInterval(tenant, sourceId, intervalSeconds)
    getSourceRegistry().register(sourceId, "sql", StubAdapter(boom=boom))
    return ingestor


def _recordOk(store, tenant, sourceId, hoursAgo, trigger="manual"):
    """走生产写口落一条 status=ok 的历史行，started_at 回拨 hoursAgo 小时。"""
    started = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(hours=hoursAgo)).isoformat()
    _recordSyncHistory(store, tenant, sourceId, trigger, "ok", started)


def _historyRows(store, tenant="default", sourceId=None):
    sql = ("SELECT * FROM enterprise_sync_history WHERE tenant_id = ?"
           + (" AND source_id = ?" if sourceId else "")
           + " ORDER BY started_at")
    params = (tenant, sourceId) if sourceId else (tenant,)
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


class TestStalenessAudit:
    def test_neverSucceededTriggersBackfill(self, kb):
        """历史无成功记录 → 审计补跑，且新增 trigger=传入 kind 的 ok 行。"""
        _saveSource(kb, "src_stale")
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report == {"checked": 1, "triggered": 1, "skipped": 0, "failed": 0}
        rows = _historyRows(kb, sourceId="src_stale")
        assert len(rows) == 1
        assert rows[0]["trigger_kind"] == "audit"
        assert rows[0]["status"] == "ok"

    def test_startupKindFlowsToHistory(self, kb):
        """启动钩子传 "startup" → 历史行 trigger_kind=startup（TEXT 列免迁移）。"""
        _saveSource(kb, "src_boot")
        report = auditEnterpriseSyncStaleness("startup", store=kb)
        assert report["triggered"] == 1
        assert _historyRows(kb, sourceId="src_boot")[0]["trigger_kind"] == "startup"

    def test_recentSuccessWithinWindowSkips(self, kb):
        """24h 内有成功 → skipped，不重复拉取（历史仍只有原成功一行）。"""
        _saveSource(kb, "src_fresh")
        _recordOk(kb, "default", "src_fresh", hoursAgo=1)
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report == {"checked": 1, "triggered": 0, "skipped": 1, "failed": 0}
        assert len(_historyRows(kb, sourceId="src_fresh")) == 1

    def test_successBeyondDefaultWindowTriggers(self, kb):
        """最近成功距今 25h（> 默认 24h）→ 视同过期，触发补跑。"""
        _saveSource(kb, "src_old")
        _recordOk(kb, "default", "src_old", hoursAgo=25)
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report["triggered"] == 1 and report["skipped"] == 0

    def test_windowEnvShrinksBehavior(self, kb, monkeypatch):
        """窗口 env 可配：2h 前的成功在默认 24h 下 skipped，窗口调小成 1h 后触发。"""
        _saveSource(kb, "src_env")
        _recordOk(kb, "default", "src_env", hoursAgo=2)
        monkeypatch.setenv("NEUROVA_ENTERPRISE_SYNC_STALE_HOURS", "1")
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report["triggered"] == 1 and report["skipped"] == 0
        rows = _historyRows(kb, sourceId="src_env")
        assert rows[-1]["trigger_kind"] == "audit"

    def test_singleSourceFailureDoesNotBlockOthers(self, kb):
        """单源 connector 抛错 → failed 计数、error 落账，其余源照常补跑。"""
        _saveSource(kb, "src_bad", boom=True)
        _saveSource(kb, "src_good")
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report["checked"] == 2
        assert report["failed"] == 1
        assert report["triggered"] == 1
        bad = _historyRows(kb, sourceId="src_bad")
        assert bad and bad[-1]["status"] == "error" and "exploded" in bad[-1]["reason"]
        good = _historyRows(kb, sourceId="src_good")
        assert good and good[-1]["status"] == "ok" and good[-1]["trigger_kind"] == "audit"

    def test_disabledSourceNotAudited(self, kb):
        """红线：停用源不进审计（不自动启用、不代跑）；同租户启用源照常审计。"""
        _saveSource(kb, "src_on")
        _saveSource(kb, "src_off", enabled=False)
        report = auditEnterpriseSyncStaleness("audit", store=kb)
        assert report["checked"] == 1
        assert _historyRows(kb, sourceId="src_off") == []


class TestStalenessAuditJob:
    def test_jobRegistrationIdempotent(self, kb, monkeypatch):
        """jobId 重复注册幂等（replace_existing 语义）；job 体调 audit("audit")。"""
        _saveSource(kb, "src_job")

        class FakeScheduler:
            def __init__(self):
                self.jobs = {}

            def addSystemJob(self, func, jobId, seconds):
                self.jobs[str(jobId)] = {"seconds": int(seconds), "func": func}

        fake = FakeScheduler()
        assert registerEnterpriseSyncAuditJob(fake) is True
        assert registerEnterpriseSyncAuditJob(fake) is True
        assert list(fake.jobs) == ["enterprise-sync-staleness-audit"]
        assert fake.jobs["enterprise-sync-staleness-audit"]["seconds"] == 86400

        # job 体真跑：走全局事实源口 → 钉到本用例的临时库
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: kb)
        fake.jobs["enterprise-sync-staleness-audit"]["func"]()
        rows = _historyRows(kb, sourceId="src_job")
        assert rows and rows[-1]["trigger_kind"] == "audit" and rows[-1]["status"] == "ok"

    def test_jobRegistrationWithoutSchedulerFacade(self):
        """无 addSystemJob 面的调度器 → 如实返回 False，不炸。"""
        assert registerEnterpriseSyncAuditJob(object()) is False
        assert registerEnterpriseSyncAuditJob(None) is False
