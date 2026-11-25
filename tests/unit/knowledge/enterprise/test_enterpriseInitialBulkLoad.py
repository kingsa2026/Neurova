# -*- coding: utf-8 -*-
"""C 维增强批 P2-4：企业源**初始批量装载**走 bulk_load 契约。

与持续同步（runOnceAsync：逐批 admitBatch、坏行只退自己）不同，初始装载
借鉴 U3 批量装载契约：**载入前全量预检（dry-run）＋整批原子（任一行违规
零落盘）＋进度回调＋游标截断续传**。判据：
- 快乐路径：多批行集一次装载全落库，游标推进，历史落账；
- dry-run：只预检零写入；
- 违规：整批零落盘、游标不推进（下轮重拉，咽喉内容键幂等兜底）；
- 截断续传：max_batches 截断后游标停在已装载处，再次调用续传余量；
- REST：仅管理员、dry_run 缺省 true。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.enterprise.fake_adapter import FakeEnterpriseAdapter
from neurova.knowledge.enterprise.registry import (
    EnterpriseIngestor,
    getSourceRegistry,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

SOURCE = "erp_prod"


@pytest.fixture(autouse=True)
def _cleanSourceRegistry():
    """本文件向**全局**源注册表注册 erp_prod——用完摘除，不污染后续测试
    （test_sourceLifecycleApi 的 health 判据依赖该源"未注册"的初始态）。"""
    yield
    registry = getSourceRegistry()
    for sourceId in (SOURCE, "erp_prod"):
        registry.unregister(sourceId)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "has_status", "kind": "relation", "domain": ["Order"]},
    ])
    return EnterpriseIngestor(store, registry=registry)


def _descriptor():
    return {"sourceId": SOURCE, "tenantId": "default", "sourceType": "sql",
            "columns": ["order_id", "status"], "logicalTable": "orders",
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"kind": "column", "column": "status"},
            "enabled": True, "agentId": "default"}


def _registerSource(ingestor, store, rows, sourceId=SOURCE):
    ingestor.saveConfig("default", sourceId, _descriptor(), enabled=True)
    adapter = FakeEnterpriseAdapter(sourceId, rows, )
    getSourceRegistry().register(sourceId, "sql", adapter)
    return adapter


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestInitialBulkLoad:
    def test_happyPathLoadsAllRowsAndAdvancesCursor(self, store, ingestor):
        """7 行 3 批：全部过咽喉落库，游标推进到末批，历史与进度如实。"""
        rows = [{"order_id": "o%d" % i, "status": "s%d" % i} for i in range(7)]
        _registerSource(ingestor, store, rows)
        progresses: list = []
        result = _run(ingestor.initialBulkLoad(
            "default", SOURCE, dryRun=False, fetchLimit=3,
            onProgress=lambda done, total: progresses.append((done, total))))
        assert result["admitted"] == 7 and result["failed"] == []
        assert result["truncated"] is False
        assert result["cursor"] == "7", "游标推进到已装载末尾"
        assert len(store.searchableFacts(agentId="default")) == 7
        assert progresses and progresses[-1] == (7, 7), "进度回调最后一拍=全量"
        history = store.queryReadOnly(
            "SELECT trigger_kind, status FROM enterprise_sync_history"
            " ORDER BY started_at DESC LIMIT 1")
        assert history[0]["trigger_kind"] == "initial_bulk"
        assert history[0]["status"] == "ok"

    def test_dryRunPrechecksWithoutLanding(self, store, ingestor):
        """dry-run：预检回执带逐行 verdict，零落库、游标不动。"""
        rows = [{"order_id": "o%d" % i, "status": "s%d" % i} for i in range(4)]
        _registerSource(ingestor, store, rows)
        result = _run(ingestor.initialBulkLoad("default", SOURCE,
                                               dryRun=True, fetchLimit=3))
        assert result["dryRun"] is True and result["total"] == 4
        assert all(p["verdict"] == "pass" for p in result["precheck"])
        assert store.searchableFacts(agentId="default") == [], "干跑零落库"
        assert (ingestor.loadConfig("default", SOURCE) or {}).get("cursor", "") \
            in ("", None), "干跑不推进游标"

    def test_violationZeroLandingAndCursorHolds(self, store, ingestor):
        """任一行违规：整批零落盘，游标不推进（下轮重拉，咽喉幂等兜底）。"""
        rows = [{"order_id": "o1", "status": "open"},
                {"order_id": "o2", "status": ""}]  # 空 object ⇒ 必填校验拒
        _registerSource(ingestor, store, rows)
        result = _run(ingestor.initialBulkLoad("default", SOURCE,
                                               dryRun=False, fetchLimit=3))
        assert result["admitted"] == 0 and result["failed"], "整批零落盘"
        assert store.searchableFacts(agentId="default") == []
        assert (ingestor.loadConfig("default", SOURCE) or {}).get("cursor", "") \
            in ("", None), "失败不推进游标"

    def test_truncationResumesFromCursor(self, store, ingestor):
        """max_batches 截断：装载已取批并推进游标；再次调用从游标续传余量。"""
        rows = [{"order_id": "o%d" % i, "status": "s%d" % i} for i in range(7)]
        _registerSource(ingestor, store, rows)
        first = _run(ingestor.initialBulkLoad("default", SOURCE, dryRun=False,
                                              fetchLimit=3, maxBatches=1))
        assert first["admitted"] == 3 and first["truncated"] is True
        assert first["cursor"] == "3", "截断批的游标已推进"
        second = _run(ingestor.initialBulkLoad("default", SOURCE, dryRun=False,
                                               fetchLimit=3, maxBatches=3))
        assert second["admitted"] == 4 and second["truncated"] is False
        assert len(store.searchableFacts(agentId="default")) == 7, \
            "续传后全量在库（内容键幂等，无重复）"

    def test_disabledSourceSkips(self, store, ingestor):
        """enabled=False：零读取零网络，如实 skipped。"""
        rows = [{"order_id": "o1", "status": "open"}]
        ingestor.saveConfig("default", SOURCE, _descriptor(), enabled=False)
        getSourceRegistry().register(SOURCE, "sql",
                                     FakeEnterpriseAdapter(SOURCE, rows))
        result = _run(ingestor.initialBulkLoad("default", SOURCE,
                                               dryRun=False))
        assert result.get("skipped") is True
        assert store.searchableFacts(agentId="default") == []


class _RegistryStub:
    """适配器注册表桩：与 KNOW-03 后的 (tenant, source) 键接口同形。"""

    def get(self, sourceId, tenantId="default", fingerprint=""):
        return None

    def unregister(self, sourceId, tenantId="default"):
        return None


class TestInitialLoadEndpoint:
    @pytest.fixture
    def client(self, store, ingestor):
        from neurova.api.endpoints import knowledge_enterprise

        app = FastAPI()
        app.include_router(knowledge_enterprise.router, prefix="/v1/knowledge")
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: {"user_id": "9", "username": "admin", "role": "admin",
                     "tenant_id": "default"}
        originalParts = knowledge_enterprise._parts
        knowledge_enterprise._parts = lambda: (ingestor, _RegistryStub(), store)
        yield TestClient(app)
        knowledge_enterprise._parts = originalParts

    def test_endpointAdminOnlyAndDryRunDefault(self, store, ingestor, client):
        """端点：仅管理员；dry_run 缺省 true（先预检后装载）。"""
        rows = [{"order_id": "o%d" % i, "status": "s%d" % i} for i in range(3)]
        _registerSource(ingestor, store, rows)
        resp = client.post(f"/v1/knowledge/enterprise/sources/{SOURCE}/initial-load")
        assert resp.status_code == 200
        assert resp.json()["data"]["result"]["dryRun"] is True, "缺省先干跑"
        assert store.searchableFacts(agentId="default") == []

    def test_endpointForbiddenForNonAdmin(self, store, ingestor, client):
        _registerSource(ingestor, store,
                        [{"order_id": "o1", "status": "open"}])
        from neurova.api.endpoints import knowledge_enterprise

        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: {
                "user_id": "2", "username": "u", "role": "user",
                "tenant_id": "default"}
        resp = client.post(
            f"/v1/knowledge/enterprise/sources/{SOURCE}/initial-load",
            json={"dry_run": False})
        assert resp.status_code == 403
