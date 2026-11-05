# -*- coding: utf-8 -*-
"""C2 红灯：更新后 facts 重抽＋异步摄取抽取补偿（SAG 对比候选 C2，2026-11-05）。

断点（SAG 对比 §4）：抽取只在同步导入与手动 backfill 触发——
① update_knowledge API 更新正文后不重抽，旧 facts 与新正文漂移只能靠
   drift 读数被动发现；
② 异步摄取路径恒 `skipped_async`（ingest_worker docstring 自认）。

接线形态（复用同一条抽取管线 `_try_extract_to_graph`，不造第二套）：
- `extract_after_update`（knowledge_ingestion）：`NEUROVA_KB_EXTRACT_ON_UPDATE`
  门控，默认 off＝旧行为；
- `extract_after_ingest`（ingest_worker）：`NEUROVA_KB_EXTRACT_ASYNC` 门控，
  默认 off＝旧行为（结果仍如实标 skipped），开时 request=None 经
  get_app_state() 解析 LLM。

抽取是增量 admit（graph_bridge 既有语义），不删旧 facts——漂移治理仍走
既有 supersede/conflict 机制，不在本批范围。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.repository import KnowledgeRepository

AGENT = "c2-test"
MODULE_INGESTION = "neurova.api.endpoints.knowledge_common"
MODULE_WORKER = "neurova.knowledge.ingest_worker"


@pytest.fixture()
def repo(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge(
        AGENT, "混合检索", "RAG 依赖 BM25 与向量检索",
        knowledge_id="k1", owner_user_id="u1",
    )
    yield repo
    # KnowledgeRepository 无显式 close；tmp 目录随测试销毁


def test_extractAfterUpdate_disabledByDefault(monkeypatch):
    """默认态＝旧行为：env 不设时不触发任何抽取调用。"""
    from neurova.api.endpoints.knowledge_common import extract_after_update

    monkeypatch.delenv("NEUROVA_KB_EXTRACT_ON_UPDATE", raising=False)
    called = []
    monkeypatch.setattr(
        MODULE_INGESTION + "._try_extract_to_graph",
        lambda *a, **k: called.append(a),
    )
    state = extract_after_update({"knowledge_id": "k1"}, None, AGENT)
    assert state == "skipped_disabled"
    assert not called, "默认关闸不得触发抽取"


def test_extractAfterUpdate_runs_whenEnabled(monkeypatch):
    """开闸：抽取被触发，条目与域参数如实传递。"""
    from neurova.api.endpoints.knowledge_common import extract_after_update

    monkeypatch.setenv("NEUROVA_KB_EXTRACT_ON_UPDATE", "on")
    captured = {}
    def spy(items, request, agent_id=None, tenant_id="default"):
        captured["items"] = items
        captured["agent_id"] = agent_id
        captured["tenant_id"] = tenant_id
    monkeypatch.setattr(MODULE_INGESTION + "._try_extract_to_graph", spy)

    item = {"knowledge_id": "k1", "title": "混合检索", "content": "新正文"}
    state = extract_after_update(item, "REQ", AGENT, tenant_id="t9")
    assert state == "extracted"
    assert captured["items"][0]["knowledge_id"] == "k1"
    assert captured["agent_id"] == AGENT
    assert captured["tenant_id"] == "t9"


def test_extractAfterUpdate_failSoft(monkeypatch):
    """抽取异常 fail-soft：返回 extract_error，不上抛打断更新返回。"""
    from neurova.api.endpoints.knowledge_common import extract_after_update

    monkeypatch.setenv("NEUROVA_KB_EXTRACT_ON_UPDATE", "on")
    def boom(items, request, agent_id=None, tenant_id="default"):
        raise RuntimeError("llm down")
    monkeypatch.setattr(MODULE_INGESTION + "._try_extract_to_graph", boom)
    assert extract_after_update({"knowledge_id": "k1"}, None, AGENT) == "extract_error"


def test_extractAfterIngest_disabledByDefault(monkeypatch):
    """异步补偿默认关闸：结果态仍是 skipped（旧行为），extractor 零调用。"""
    from neurova.knowledge.ingest_worker import extract_after_ingest

    monkeypatch.delenv("NEUROVA_KB_EXTRACT_ASYNC", raising=False)
    called = []
    monkeypatch.setattr(
        MODULE_INGESTION + "._try_extract_to_graph",
        lambda *a, **k: called.append(a),
    )
    state = extract_after_ingest({"agent_id": AGENT}, ["k1"])
    assert state == "skipped_disabled"
    assert not called


def test_extractAfterIngest_runs_whenEnabled(monkeypatch, repo):
    """开闸：从仓库取回条目后触发抽取；请求上下文为 None（生产走 app state）。"""
    from neurova.knowledge.ingest_worker import extract_after_ingest

    monkeypatch.setenv("NEUROVA_KB_EXTRACT_ASYNC", "on")
    captured = {}
    def spy(items, request, agent_id=None, tenant_id="default"):
        captured["items"] = [dict(i) for i in items]
        captured["agent_id"] = agent_id
        captured["request"] = request
    monkeypatch.setattr(MODULE_INGESTION + "._try_extract_to_graph", spy)
    monkeypatch.setattr(MODULE_WORKER + ".get_knowledge_repository", lambda: repo)

    state = extract_after_ingest({"agent_id": AGENT}, ["k1"])
    assert state == "extracted"
    assert captured["items"][0]["knowledge_id"] == "k1"
    assert captured["agent_id"] == AGENT
    assert captured["request"] is None


def test_extractAfterIngest_missingItems(monkeypatch, repo):
    """条目已被清理（墓碑）时如实报 skipped_missing_items，不空跑。"""
    from neurova.knowledge.ingest_worker import extract_after_ingest

    monkeypatch.setenv("NEUROVA_KB_EXTRACT_ASYNC", "on")
    called = []
    monkeypatch.setattr(
        MODULE_INGESTION + "._try_extract_to_graph",
        lambda *a, **k: called.append(a),
    )
    monkeypatch.setattr(MODULE_WORKER + ".get_knowledge_repository", lambda: repo)
    assert extract_after_ingest({"agent_id": AGENT}, ["ghost"]) == "skipped_missing_items"
    assert not called
