# -*- coding: utf-8 -*-
"""W3 持续同步（specs/2026-11-12 §5）：enterprise 源 interval job 注册。

向既有 agent/scheduler 注册 interval job（不新造调度器）；job 触发调既有
runOnceAsync 处理函数（零新同步逻辑）；非零间隔才注册；假 scheduler 断言。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    registerIntervalSyncs,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


class FakeScheduler:
    """addSystemJob 契约的假件：记录 (jobId, seconds, func)。"""

    def __init__(self):
        self.jobs = []

    def addSystemJob(self, func, jobId, seconds):
        self.jobs.append({"jobId": str(jobId), "seconds": int(seconds), "func": func})


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _saveSource(store, sourceId, enabled=True, intervalSeconds=0):
    ingestor = EnterpriseIngestor(store)
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    OntologyTermRegistry(store).register("row", "relation")
    descriptor = {
        "sourceType": "sql",
        "sourceId": sourceId,
        "dialect": "sqlite",
        "database": "legacy.db",
        "cursorColumn": "id",
        "columns": ["id"],
        "subject": {"column": "id"},
        "predicate": {"termId": "row"},
        "object": {"column": "id", "kind": "column"},
    }
    ingestor.saveConfig("default", sourceId, descriptor, enabled=enabled)
    if intervalSeconds:
        ingestor.setSyncInterval("default", sourceId, intervalSeconds)


class TestIntervalSync:
    def test_nonZeroIntervalRegistersJob(self, kb):
        _saveSource(kb, "src_a", enabled=True, intervalSeconds=300)
        fake = FakeScheduler()
        registerIntervalSyncs(fake, store=kb)
        assert len(fake.jobs) == 1
        assert fake.jobs[0]["jobId"] == "kb_enterprise_sync_src_a"
        assert fake.jobs[0]["seconds"] == 300
        assert callable(fake.jobs[0]["func"])

    def test_zeroIntervalAndDisabledSkip(self, kb):
        _saveSource(kb, "src_b", enabled=True, intervalSeconds=0)
        _saveSource(kb, "src_c", enabled=False, intervalSeconds=120)
        fake = FakeScheduler()
        registerIntervalSyncs(fake, store=kb)
        assert fake.jobs == [], "零间隔与停用源不注册"

    def test_jobCallsExistingRunOnce(self, kb, monkeypatch):
        """job 触发即调既有 runOnceAsync（零新同步逻辑）。"""
        _saveSource(kb, "src_d", enabled=True, intervalSeconds=60)
        fake = FakeScheduler()
        registerIntervalSyncs(fake, store=kb)
        called = []

        async def fakeRunOnce(self, tenant, sourceId):
            called.append((tenant, sourceId))
            return {"admitted": 0, "rejected": 0, "rejections": [], "cursor": ""}

        monkeypatch.setattr(EnterpriseIngestor, "runOnceAsync", fakeRunOnce)
        job = fake.jobs[0]["func"]
        job()  # job 是同步包装（内部自管事件循环）
        assert called, "job 触发应调 runOnceAsync"
        assert called[0][1] == "src_d"

    def test_schedulerHasSystemJobHook(self):
        """既有调度器带 addSystemJob 公开面（不新造调度器）。"""
        from neurova.agent.scheduler import TaskScheduler

        assert hasattr(TaskScheduler, "addSystemJob"), \
            "scheduler 需提供系统级 job 注册口（W3）"

    def test_setSyncIntervalPersists(self, kb):
        _saveSource(kb, "src_e", enabled=True)
        ingestor = EnterpriseIngestor(kb)
        ingestor.setSyncInterval("default", "src_e", 900)
        config = ingestor.loadConfig("default", "src_e")
        assert config.get("sync_interval_seconds") == 900
        with kb._lock:
            row = kb._conn.execute(
                "SELECT sync_interval_seconds FROM enterprise_source_configs"
                " WHERE source_id = 'src_e'").fetchone()
        assert int(row["sync_interval_seconds"]) == 900, "v44 列落库"
