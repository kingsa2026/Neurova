# -*- coding: utf-8 -*-
"""KNOW-08：知识摄取队列全链携带租户。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-08）：schema、dedupe、enqueue、
worker 均无 tenant——同用户跨租户同内容互相去重，异步抽取落 default。
判据：事件行带租户、dedupe 按租户分区、worker 以事件租户构建导入身份，
真实导入链落条目进事件租户；观测、span 与取消按 uid+tenant 圈域。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ingest_queue import KnowledgeIngressQueue
from neurova.knowledge.ingest_worker import process_ingress_event


@pytest.fixture
def queue(tmp_path):
    q = KnowledgeIngressQueue(db_path=tmp_path / "q.db",
                              files_dir=tmp_path / "files")
    yield q
    q.close()


class TestQueueTenant:
    def test_enqueueCarriesTenant(self, queue):
        task = queue.enqueue_upload("a.txt", b"content", agent_id="default",
                                    user_id="u1", tenant_id="acme")
        row = queue.get(task["task_id"])
        assert row["tenant_id"] == "acme", "事件行必须带租户"

    def test_dedupeSeparatesTenants(self, queue):
        """同用户同内容跨租户不得互相去重（旧键无租户→第二租户被 replay 吞掉）。"""
        t1 = queue.enqueue_upload("a.txt", b"same", agent_id="default",
                                  user_id="u1", tenant_id="t1")
        t2 = queue.enqueue_upload("a.txt", b"same", agent_id="default",
                                  user_id="u1", tenant_id="t2")
        assert t2["task_id"] != t1["task_id"], "跨租户同内容各自成任务"
        assert not t2.get("replayed"), "跨租户投递不得被旧任务吞掉"

    def test_urlEnqueueCarriesTenant(self, queue):
        task = queue.enqueue_url(url="https://example.com/x", title_hint="x",
                                 agent_id="default", user_id="u1",
                                 tenant_id="acme")
        assert queue.get(task["task_id"])["tenant_id"] == "acme"

    def test_observationMethodsEnforceUserAndTenant(self, queue):
        acme = queue.enqueue_upload("a.txt", b"acme", "default", "u1", "acme")
        beta = queue.enqueue_upload("b.txt", b"beta", "default", "u1", "beta")
        queue.enqueue_upload("c.txt", b"other", "default", "u2", "acme")
        queue.record_span(acme["task_id"], "parse", "done")
        queue.record_span(beta["task_id"], "parse", "done")

        assert [row["task_id"] for row in queue.list_recent(
            user_id="u1", tenant_id="acme")] == [acme["task_id"]]
        assert queue.stats(user_id="u1", tenant_id="acme")["pending"] == 1
        assert queue.get(beta["task_id"], user_id="u1", tenant_id="acme") is None
        assert queue.get_spans(
            beta["task_id"], user_id="u1", tenant_id="acme") == []
        assert queue.cancel_task(
            beta["task_id"], by="u1", user_id="u1", tenant_id="acme") is False
        assert queue.get(beta["task_id"])["status"] == "pending"


class TestWorkerTenant:
    def test_workerBuildsTenantBearingUser(self, tmp_path):
        """worker 给导入器的身份必须带事件租户（旧实现只有 user_id/role）。"""
        captured = {}

        def importer(data, filename, agent_id, user):
            captured["user"] = dict(user)
            return [{"knowledge_id": "k1"}], "ok"

        note = tmp_path / "a.txt"
        note.write_text("正文", encoding="utf-8")
        event = {"source": "upload", "agent_id": "default", "user_id": "u1",
                 "tenant_id": "acme", "filename": "a.txt",
                 "storage_path": str(note)}
        result = process_ingress_event(event, importer=importer)
        assert result["ok"], result
        assert captured["user"].get("tenant_id") == "acme", \
            "异步导入身份必须继承事件租户"

    def test_workerLandsInEventTenant(self, tmp_path, monkeypatch):
        """真实导入链：worker 产出的条目落在事件租户，不落 default。"""
        from neurova.api.endpoints import knowledge_ingestion
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        monkeypatch.setattr(knowledge_ingestion, "get_repository", lambda: repo)
        note = tmp_path / "note.txt"
        note.write_text("租户隔离正文", encoding="utf-8")
        event = {"source": "upload", "agent_id": "default", "user_id": "u1",
                 "tenant_id": "acme", "filename": "note.txt",
                 "storage_path": str(note)}

        result = process_ingress_event(
            event, importer=knowledge_ingestion._import_file_data)

        assert result["ok"], result
        found = repo.find_item(result["item_ids"][0])
        assert found is not None, "条目已入库"
        assert str(found[1].get("tenant_id") or "") == "acme", \
            "异步抽取必须落在事件租户，而不是 default"
