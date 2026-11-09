# -*- coding: utf-8 -*-
"""3D 探索器的服务端子图裁剪（升级计划 S4 后端半）。

验收（§11.4 S4）：服务端按 focus/跳数/类型/上限裁剪——3D 画布不拉全量图，
N 节点渲染预算由服务端先兜住。判据：
- focus 必填、不存在 404；
- hops=1 的 BFS 只含直接邻居，边不越过裁剪边界；
- types 过滤节点类型；limit 截断如实报 truncated。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge_graph_api as kg_module
from neurova.core import app_settings
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager, NodeType, RelationType,
)

USER = {"user_id": "1", "username": "a", "role": "admin",
        "tenant_id": "t1", "neuser_id": "1"}
PREFIX = "/api/v1/knowledge-graph"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mgr = KnowledgeGraphManager(auto_save=False)
    a = mgr.add_node(label="A", node_type=NodeType.CONCEPT).node_id
    b = mgr.add_node(label="B", node_type=NodeType.CONCEPT).node_id
    c = mgr.add_node(label="C", node_type=NodeType.ENTITY).node_id
    d = mgr.add_node(label="D", node_type=NodeType.CONCEPT).node_id
    for src, dst in ((a, b), (b, c), (c, d)):
        mgr.add_edge(src, dst, relation_type=RelationType.RELATED_TO)
    monkeypatch.setattr(
        kg_module, "_get_kg_manager",
        lambda agent_id="default", tenant_id="default": mgr)
    app = FastAPI()
    app.include_router(kg_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(USER)
    return TestClient(app), {"A": a, "B": b, "C": c, "D": d}


class TestSubgraphClipping:

    def testNoFocusReturnsClippedWhole(self, client):
        """首屏无焦点：不 422，按 limit 裁剪全图（同一端点两种模式）。"""
        http, _ids = client
        resp = http.get(PREFIX + "/agent/subgraph", params={"limit": 3})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3
        assert data["truncated"] is True

    def testUnknownFocusIs404(self, client):
        http, _ = client
        resp = http.get(PREFIX + "/agent/subgraph", params={"focus": "nope"})

        assert resp.status_code == 404, resp.text

    def testOneHopKeepsOnlyNeighbors(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 1})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        labels = {n["label"] for n in data["nodes"]}
        assert labels == {"A", "B", "C"}
        # 边不越过裁剪边界：C-D 不在返回里。
        assert all({e["source"], e["target"]} <= {ids["A"], ids["B"], ids["C"]}
                   for e in data["edges"])
        assert data["truncated"] is False

    def testTypeFilterNarrowsNodes(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 2,
                                "types": "concept"})

        assert resp.status_code == 200, resp.text
        labels = {n["label"] for n in resp.json()["data"]["nodes"]}
        assert "C" not in labels
        assert {"A", "B", "D"} <= labels

    def testLimitReportsTruncation(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 2, "limit": 2})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 2
        assert data["truncated"] is True
        assert data["stats"]["node_count"] == 4

    def testHopsBeyondDiameterYieldsReachableClip(self, client):
        """hops 超过图直径：结果=可达集按 limit 截断，truncated 如实，不炸。
        同时咬合 BFS 提前终止——收录满 limit 后不再继续扩展层。"""
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 12, "limit": 3})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3
        assert data["truncated"] is True

    def testFocusAlwaysIncluded(self, client):
        http, ids = client
        resp = http.get(PREFIX + "/agent/subgraph",
                        params={"focus": ids["B"], "hops": 0, "limit": 1})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert {n["label"] for n in data["nodes"]} == {"B"}


class TestLimitFollowsGlobalSetting:
    """渲染上限单源（教义第 6 条）：显式参数 > 全局设置 advanced.graph_studio_limit > 200。

    用户实测：真总量 250 节点被默认 200 恒截断，截断提示让人「去调大 limit」
    却没有任何设置入口——上限收成全局设置（高级设置卡），图谱读面端点缺省跟读，
    前端三处写死值（3D 500 / 焦点邻域 200 / studio 不传吃后端 200）一并退役。
    """

    def _pinSetting(self, monkeypatch, value):
        monkeypatch.setattr(
            app_settings, "get_advanced_settings",
            lambda path=None: {"graph_studio_limit": value})

    def _stubStudioSchema(self, monkeypatch):
        # studio 端点在 handler 内组装本体 schema（真连知识事实库）——与 limit
        # 无关的装配面，钉栅栏缝隙：注入空 schema，红留给节点数断言。
        from neurova.api.endpoints import knowledge_ontology

        monkeypatch.setattr(
            knowledge_ontology, "ontologySchemaData",
            lambda tenant_id=None: {"terms": [], "rules": []})

    def testSubgraphDefaultFollowsSetting(self, client, monkeypatch):
        http, _ids = client
        self._pinSetting(monkeypatch, 3)
        resp = http.get(PREFIX + "/agent/subgraph")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3, "缺省 limit 必须跟随全局设置，而非写死 200"
        assert data["truncated"] is True

    def testStudioDefaultFollowsSetting(self, client, monkeypatch):
        """工作台首屏（用户截断提示的出处）：不传 limit 时同样跟设置。"""
        http, _ids = client
        self._pinSetting(monkeypatch, 3)
        self._stubStudioSchema(monkeypatch)
        resp = http.get(PREFIX + "/agent/studio")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 3, "studio 缺省 limit 必须跟随全局设置"
        assert data["truncated"] is True

    def testExplicitLimitStillWins(self, client, monkeypatch):
        """显式查询参数最优先——设置只补缺省，不改 API 契约。"""
        http, _ids = client
        self._pinSetting(monkeypatch, 3)
        resp = http.get(PREFIX + "/agent/subgraph", params={"limit": 2})

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 2
        assert data["truncated"] is True

    def testSettingBeyondCapClampedToEndpointCap(self, client, monkeypatch):
        """设置只经设置面写（无 le 校验），端点必须按同一上限 2000 钳住，
        不能让设置面绕过查询参数的合法域。"""
        http, _ids = client
        self._pinSetting(monkeypatch, 99999)
        resp = http.get(PREFIX + "/agent/subgraph")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["nodes"]) == 4, "钳制后上限(2000) ≥ 全图 4 节点，应全量收录"
        assert data["truncated"] is False

    def testSettingGarbageFallsBackToDefault200(self, client, monkeypatch):
        http, _ids = client
        self._pinSetting(monkeypatch, "abc")
        resp = http.get(PREFIX + "/agent/subgraph")

        assert resp.status_code == 200, resp.text
        assert len(resp.json()["data"]["nodes"]) == 4, "非数值设置回退默认 200 ≥ 全图"

    def testResolutionClampDomains(self, monkeypatch):
        """解析函数的合法域钉：设置超顶钳 2000、负值钳 1、垃圾回 200、显式直通。
        （4 节点夹具量不出 2000 级钳制，这格在解析单元上补齐端点量不到的域。）"""
        self._pinSetting(monkeypatch, 99999)
        assert kg_module._effectiveSubgraphLimit(None) == 2000
        self._pinSetting(monkeypatch, -5)
        assert kg_module._effectiveSubgraphLimit(None) == 1
        self._pinSetting(monkeypatch, "abc")
        assert kg_module._effectiveSubgraphLimit(None) == 200
        self._pinSetting(monkeypatch, 3)
        assert kg_module._effectiveSubgraphLimit(7) == 7
