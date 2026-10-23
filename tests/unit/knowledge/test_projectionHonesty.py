# -*- coding: utf-8 -*-
"""投影面的三处不诚实（§6-106 复算时抓出，用户 2026-10-09 点单三条一起处理）。

风险 1（假成功，教义第 2 条禁物）：`KnowledgeGraphManager._save` 是
`except Exception: logger.error(...)`。真库那次 rebuild 期间实测出现 3 次
`[WinError 5] 拒绝访问`（`.tmp → 正式文件` 改名被拒），而端点照样回 `code:0 success`——
内存与磁盘分叉这件事对调用方完全不可见。这次磁盘终态恰好是对的（后续某次整体写成功），
但那是不能被保证的巧合。修法不是"少吞一次异常"那么轻：8 个 mutation 调用点都靠
auto-save 副作用落盘，逐个改成会抛等于把"内存改成功、磁盘没落地"变成半截事务现场。
所以收口成**显式持久化 + 回执**：`persist()` 由编排方（rebuild）在收尾时要一次，
它的成败决定端点回 200 还是 500。

风险 2（探针口径比名字窄）：`projectionDrift` 只比**关系**。清账后实测仍有
33 个无邻居的孤立节点，个个带 `description`（条目正文前 200 字），而 drift 回
`missing/orphan 都是空`。端点回的 `nodes:145` 是"按权威铺出来的节点数"，
不是投影总节点数（178）——两个数不同名却同城，读的人必然混。

风险 3（下次漂移没人会知道）：用户裁定接启动、**只报不修**。所以判据要同时钉两件事：
漂了必须 WARN 点名，且这一步**不许动数据**（修是 `projection/rebuild` 的职责，
报与修混成一件事，读的人就再也看不到曾经分叉过——这句是 graph_bridge 原话）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    NodeType,
    reset_agent_knowledge_graph_managers,
)
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
from neurova.knowledge.graph_bridge import (
    projectionDrift,
    rebuildProjectionFromAuthority,
)

_GHOST_BODY = "青梧孤立节点正文摘要"


def _store(tmp_path) -> KnowledgeFactStore:
    return KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))


def _admit(store, subject, predicate, obj):
    gate = productionAdmissionGate(store, toolVersion="unit")
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        activityKind="extract", activityBasis="unit:projection-honesty",
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:projection-honesty",
                     "statementText": content}],
    )).factId


def _seedOneRelation(store, graph, ghosts=3):
    """权威侧 1 条关系（两端都是主体），投影侧另摆 N 个无据孤立节点。"""
    _admit(store, "青梧乙", "is_a", "文档集合")          # 让"青梧乙"成为主体
    _admit(store, "青梧甲", "part_of", "青梧乙")
    a = graph.add_node(label="青梧甲", node_type=NodeType.CONCEPT.value)
    b = graph.add_node(label="青梧乙", node_type=NodeType.CONCEPT.value)
    graph.add_edge(source_id=a.node_id, target_id=b.node_id, relation_type="part_of")
    for i in range(ghosts):
        graph.add_node(label="无据节点%d" % i, node_type=NodeType.CONCEPT.value,
                       properties={"description": "%s %d" % (_GHOST_BODY, i)})


class TestPersistIsHonest:
    def test_persistReturnsFailureReceiptWhenDiskWriteFails(self, tmp_path, monkeypatch):
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "graph"))
        graph.add_node(label="青梧甲", node_type=NodeType.CONCEPT.value)

        def _refuse(path, text, *a, **kw):
            raise OSError(5, "拒绝访问")

        monkeypatch.setattr("neurova.core.atomic_io.atomic_write_text", _refuse)
        receipt = graph.persist()

        assert receipt["ok"] is False, "落盘失败仍报成功——端点的假成功就长在这一格"
        assert set(receipt["failed"]) == {"nodes", "edges"}, receipt
        assert "拒绝访问" in receipt["detail"]

    def test_lastSaveOutcomeStaysReadableForCallers(self, tmp_path, monkeypatch):
        """吞掉不等于没事：至少要让调用方读得到"上一次落盘成没成"。"""
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "graph"))
        graph.add_node(label="青梧甲", node_type=NodeType.CONCEPT.value)
        assert graph.lastSaveOutcome()["ok"] is True

        def _refuse(path, text, *a, **kw):
            raise OSError(5, "拒绝访问")

        monkeypatch.setattr("neurova.core.atomic_io.atomic_write_text", _refuse)
        graph.add_node(label="青梧乙", node_type=NodeType.CONCEPT.value)

        assert graph.lastSaveOutcome()["ok"] is False, (
            "auto-save 失败后无从复核——内存与磁盘分叉变成不可见状态")

    def test_rebuildOutcomeCarriesThePersistReceipt(self, tmp_path, monkeypatch):
        store, graph = _store(tmp_path), KnowledgeGraphManager(storage_dir=str(tmp_path / "graph"))
        try:
            _seedOneRelation(store, graph)

            def _refuse(path, text, *a, **kw):
                raise OSError(5, "拒绝访问")

            monkeypatch.setattr("neurova.core.atomic_io.atomic_write_text", _refuse)
            outcome = rebuildProjectionFromAuthority("default", graph, store)

            assert outcome["persist"]["ok"] is False, (
                "重建说铺好了而磁盘没落地——正是 §6-106 那三行 WinError 的形态")
        finally:
            store.close()


class TestDriftSeesNodes:
    def test_driftReportsUnbackedNodesAndTheirBodyText(self, tmp_path):
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "graph"))
        try:
            _seedOneRelation(store, graph, ghosts=3)

            drift = projectionDrift("default", graph, store)

            assert len(drift["missing_relations"]) == 0 and len(drift["orphan_relations"]) == 0, (
                "本夹具的关系账是平的，读数不该带关系差——先证实测的是节点这一维")
            assert len(drift["unbacked_nodes"]) == 3, drift
            assert drift["unbacked_nodes_with_body"] == 3, (
                "无据节点还带着条目正文摘要，探针不许只报关系是平的")
            assert drift["projection_nodes"] == 5 and drift["authority_nodes"] == 2
        finally:
            store.close()

    def test_backedNodesAreNotCountedAsUnbacked(self, tmp_path):
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "graph"))
        try:
            _seedOneRelation(store, graph, ghosts=0)
            drift = projectionDrift("default", graph, store)
            assert len(drift["unbacked_nodes"]) == 0, drift["unbacked_nodes"]
        finally:
            store.close()


class TestStartupReportsWithoutTouchingData:
    """启动只报不修（用户 2026-10-09 裁定接启动，但不接写路径）。"""

    def _boot(self, tmp_path, monkeypatch):
        # per-agent 管理器是进程级缓存：不清就把上一个用例的目录带进来，
        # "启动看到分叉"会在两个用例之间互相污染（第一版就是这么假绿/假红过）
        reset_agent_knowledge_graph_managers()
        # 门面注成隔离实例：`get_knowledge_fact_store()` 的默认路径由**导入期**的
        # PRODUCTION_STORAGE_DIR 定，pytest 围栏当场抛 RuntimeError——启动那段的 fail-open
        # 会把它记成"本轮没有巡检读数"，于是这一格绿得什么都没测。
        isolated = _store(tmp_path)
        self._open = getattr(self, '_open', [])
        self._open.append(isolated)
        monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                            lambda *a, **kw: isolated)
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "ws"))
        # v2 布局：知识图谱随 agent 工作区落在 data/<id>/workspaces/ 下
        # （4bf9b733 统一私有落点；旧路径的迁移由 agent_layout_migration 负责）。
        graphDir = tmp_path / "ws" / "default" / "workspaces" / "knowledge_graph"
        graphDir.mkdir(parents=True, exist_ok=True)
        (graphDir / "nodes.json").write_text(json.dumps(
            [{"node_id": "n1", "label": "无据节点", "node_type": "concept",
              "properties": {"description": _GHOST_BODY}}], ensure_ascii=False),
            encoding="utf-8")
        (graphDir / "edges.json").write_text("[]", encoding="utf-8")
        return graphDir, {p: p.read_bytes() for p in (graphDir / "nodes.json",
                                                     graphDir / "edges.json")}

    def test_startupWarnsWhenProjectionIsUnbacked(self, tmp_path, monkeypatch, caplog):
        graphDir, snapshot = self._boot(tmp_path, monkeypatch)
        from neurova.api.app import create_app

        with caplog.at_level("WARNING"):
            with TestClient(create_app()):
                pass

        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "投影" in text and "无据" in text, (
            "漂了却没点名——下一次没人知道分叉过。读数见 caplog：%s" % text[:200])
        for p, before in snapshot.items():
            assert p.read_bytes() == before, "启动只报不修：不许动投影文件"
        assert graphDir.name == "knowledge_graph"

    def test_startupStaysQuietWhenNothingIsDrifted(self, tmp_path, monkeypatch, caplog):
        """投影目录存在且与（空）权威一致时必须报"无分叉"，而不是不吭声。

        只断"没有 WARN"会让这条判据在整段巡检根本没跑起来时也绿——所以正向钉那行
        "一致性巡检：无分叉"：它证明巡检真的跑了、真的看过这份投影。
        """
        graphDir, _snapshot = self._boot(tmp_path, monkeypatch)
        (graphDir / "nodes.json").write_text("[]", encoding="utf-8")
        reset_agent_knowledge_graph_managers()
        from neurova.api.app import create_app

        with caplog.at_level("INFO"):
            with TestClient(create_app()):
                pass

        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "无据" not in text, "没有分叉却报分叉——巡检一旦狼来了就没人信"
        assert "一致性巡检：无分叉" in text, (
            "读不到无分叉这行，说明巡检根本没跑——不吭声不等于太平")

    def teardown_method(self):
        for store in getattr(self, "_open", []):
            store.close()
