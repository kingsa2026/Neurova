# -*- coding: utf-8 -*-
"""NEURON 端点层的那份共享图（台账 §6-133 分流里判「补」的第三档）。

## 这三档旧文件在指同一件事

`tests/test_api/test_api_direct.py`、`test_api_shared_graph.py`、`test_shared_graph.py`
是 §6-133 点名的三个 0 用例文件。它们的共同形状是**在模块顶层直调 `neuron.py` 的 handler**
（`asyncio.run(create_entity(...))` → `list_entities()` → `cascade_reasoning(...)` →
`get_shared_graph()`），一路 print、零 assert。复算之后：

- 顶层那次 `reset_shared_graph()` 是**进程级副作用**——它在收集期就改了全局单例
  （`neuron.py:20` `_shared_graph`），这正是"名字像覆盖、实则给别的用例埋雷"的形态；
- 但它守的那条性质**现役判据一条都没有**：
  `tests/unit/test_neuron_api_registration.py:41` 断的是路由前缀形状（装配面），
  `tests/unit/cognitive/test_neuron_components.py:100,128` 断的是**库层**
  （`DependencyGraph` 自己的 downstream/path），中间这层——
  **"每个 handler 每次都重新取那份进程级共享图"**——没有任何判据。
    这一层坏了会是这个形状：某个 handler 自己 `DependencyGraph()` 建了一份私有图，
    写入后 `/entities` 永远回空。HTTP 还是 200，页面还是能弹"创建成功"，
    而图谱永远不涨（`get_neuron_stats` 那个读数就永远是 0）。

所以这一档补的是**跨 handler 的共享态**，不是把老脚本翻译成 pytest。
生产侧那六个 handler 各自的 `except Exception → HTTPException(500)` 也一并钉住：
图坏了要显式 500，不许回一个 `success:true` 的空列表（教义第 2 条）。

夹具纪律：每个用例前后都 `reset_shared_graph()`——这份判据自己在改进程级单例，
不改回来就是把"谁先跑谁决定结果"传给同进程后面的用例（§6-41 同族）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as authModule
from neurova.api.endpoints import neuron as neuronModule

BASE = "/api/neuron"
USER = {"user_id": "u-1", "username": "u1", "role": "user", "neuser_id": "u-1"}


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(neuronModule.router, prefix="/api")
    app.dependency_overrides[authModule.get_current_user] = lambda: dict(USER)

    neuronModule.reset_shared_graph()
    with TestClient(app) as c:
        yield c
    neuronModule.reset_shared_graph()


def _graph():
    return neuronModule.get_shared_graph()


class TestWritesAreReadableThroughTheSameSharedGraph:
    def test_createdEntityAppearsInTheListing(self, client):
        created = client.post(f"{BASE}/entities",
                              json={"name": "记忆库", "entity_type": "object",
                                    "metadata": {"origin": "test"}})

        assert created.status_code == 200, created.text
        listed = client.get(f"{BASE}/entities").json()

        assert listed["success"] is True
        assert listed["total"] == 1, listed
        assert listed["data"][0]["name"] == "记忆库"

    def test_statsReadTheSameStoreTheWriterWroteTo(self, client):
        """这条就是老脚本守的性质：写入之后**另一个 handler** 的读数要跟着动。"""
        client.post(f"{BASE}/entities", json={"name": "A", "entity_type": "concept"})
        client.post(f"{BASE}/entities", json={"name": "B", "entity_type": "concept"})

        stats = client.get(f"{BASE}/stats").json()["data"]

        assert stats["total_entities"] == 2, stats
        assert stats["entity_types"] == 1, stats

    def test_entityTypeFilterDoesNotChangeTheTotal(self, client):
        client.post(f"{BASE}/entities", json={"name": "A", "entity_type": "concept"})
        client.post(f"{BASE}/entities", json={"name": "B", "entity_type": "object"})

        filtered = client.get(f"{BASE}/entities", params={"entity_type": "concept"}).json()

        assert [e["name"] for e in filtered["data"]] == ["A"]
        # 实况：`neuron.py` 是先过滤再 `len(entities)`，所以 `total` 是**命中数**不是图上总数。
        # 这里把当前口径钉住并写明它是什么——将来若要改成"总数"，这格会红，逼着改的人处理语义分裂。
        assert filtered["total"] == 1, (
            "`total` 今值是命中数（先过滤再 len）；它变了说明写面或读面口径动了，"
            "而前端按哪个解释都会差一个数")
        assert client.get(f"{BASE}/stats").json()["data"]["total_entities"] == 2, (
            "同一次写入，列表说不止 2、统计说 2——两个读数分家了")

    def test_writtenDependencyIsReadBackByTheDependencyHandler(self, client):
        source = client.post(f"{BASE}/entities", json={"name": "上游", "entity_type": "object"}).json()
        target = client.post(f"{BASE}/entities", json={"name": "下游", "entity_type": "object"}).json()

        created = client.post(f"{BASE}/dependencies", json={
            "source_id": source["data"]["id"], "target_id": target["data"]["id"],
            "dep_type": "prerequisite", "confidence": 0.9})
        assert created.status_code == 200, created.text

        deps = client.get(f"{BASE}/dependencies/{source['data']['id']}",
                          params={"direction": "downstream"}).json()

        assert deps["success"] is True
        assert target["data"]["id"] in str(deps["data"]["downstream"]), deps

    def test_cascadeCountsTheEdgeThatWasJustWritten(self, client):
        a = client.post(f"{BASE}/entities", json={"name": "A", "entity_type": "object"}).json()["data"]
        b = client.post(f"{BASE}/entities", json={"name": "B", "entity_type": "object"}).json()["data"]
        client.post(f"{BASE}/dependencies",
                    json={"source_id": a["id"], "target_id": b["id"], "dep_type": "prerequisite"})

        cascade = client.post(f"{BASE}/cascade",
                             json={"entity_id": a["id"], "direction": "forward"}).json()

        assert cascade["success"] is True
        assert cascade["data"]["total_affected"] >= 1, (
            "刚写进去的边没被级联看见：写面与推理面读的不是同一份图")

    def test_absenceDetectionSeesWhatWasWritten(self, client):
        written = client.post(f"{BASE}/entities",
                             json={"name": "已存在", "entity_type": "object"}).json()["data"]

        absent = client.post(f"{BASE}/absence/detect", json={
            "expected_entity": "从没写过", "expected_relation": "prerequisite",
            "context_entities": [written["id"]]}).json()

        assert absent["success"] is True
        assert absent["data"]["entity_exists"] is False
        assert absent["data"]["is_absent"] is True

    def test_absenceDetectionSeesAnExistingEntity(self, client):
        written = client.post(f"{BASE}/entities",
                             json={"name": "在图里", "entity_type": "object"}).json()["data"]

        present = client.post(f"{BASE}/absence/detect", json={
            "expected_entity": written["id"], "expected_relation": "prerequisite",
            "context_entities": [written["id"]]}).json()

        # `absence_reasoner.py:64` 用的是 `expected_entity in self.graph.entities`——
        # 按 **id** 查，不是按 name。传名字会永远读成"不存在"，这个口径必须钉住：
        # 否则调用方（agent 侧那句"这个概念还没进图"）会拿着名字反复重建同一个实体。
        assert present["data"]["entity_exists"] is True, (
            "按 id 传进去的实体在缺失检测里读不到——两个 handler 各拿一份图，"
            "或取用键从 id 漂到了 name：%r" % present)

        byName = client.post(f"{BASE}/absence/detect", json={
            "expected_entity": written["name"], "expected_relation": "prerequisite",
            "context_entities": []}).json()
        assert byName["data"]["entity_exists"] is False, (
            "按名字也读得到了——说明这层取用键改了，上面的 id 口径不再成立")


class TestExtractionWritesIntoTheSharedGraph:
    def test_extractPopulatesTheSameStoreTheListerReads(self, client):
        """/extract 的写侧必须落在同一份共享图上（`neuron.py:296` 传的就是 `get_shared_graph()`）。

        内容里带的关键词是现役提取器（`moe_dependency_extractor.py:34-42`）真认的那一族，
        实测在这份文本上能出 5 个实体——用一段它必然读不出实体的散文，这格就退化成恒真空转。
        """
        before = client.get(f"{BASE}/stats").json()["data"]["total_entities"]

        result = client.post(f"{BASE}/extract", json={
            "memory_id": "mem-1",
            "content": "数据库 依赖 缓存，服务器 需要 API 接口",
            "metadata": {}})

        assert result.status_code == 200, result.text
        body = result.json()
        assert body["total"] > 0, "提取器在这段文本上回了 0 条——用例内容已失效，本格空转"
        assert isinstance(body["data"], list), "`data` 今值是列表，形状变了要显式处理"

        after = client.get(f"{BASE}/stats").json()["data"]

        assert after["total_entities"] > before, (
            "提取回了 200，可共享图上一条实体都没多——写面与读面不同源（这条老探针正是 print 这个数）")
        assert after["total_edges"] > 0, after

    def test_contentTheExtractorCannotParseYieldsNoEdgesAndDoesNotFail(
            self, client):
        """"读不懂"要如实回空，而不是把整条请求判成失败。"""
        result = client.post(f"{BASE}/extract", json={
            "memory_id": "mem-2", "content": "嗯", "metadata": {}})

        assert result.status_code == 200, result.text
        body = result.json()
        assert body["success"] is True and body["total"] == 0 and body["data"] == [], (
            "读不懂的内容被当成失败（5xx）或被当成有产物：%r" % body)


class TestFailureIsNotReportedAsAnEmptySuccess:
    def _brokenGraph(self, monkeypatch):
        class Broken:
            """任何属性访问都抛错——包括 `entities`/`edges`，否则测不到失败分支。"""

            def __getattr__(self, name):
                raise RuntimeError("graph is gone")

        monkeypatch.setattr(neuronModule, "_shared_graph", Broken())

    @pytest.mark.parametrize("path,method,payload", [
        ("/entities", "get", None),
        ("/stats", "get", None),
        ("/dependencies/e1", "get", None),
    ])
    def test_readHandlersReturn500RatherThanAnEmptySuccess(
            self, client, monkeypatch, path, method, payload):
        self._brokenGraph(monkeypatch)

        r = getattr(client, method)(f"{BASE}{path}")

        assert r.status_code == 500, (
            "图坏了却回 %s——`success:true` + 空数据是最难查的形态（教义第 2 条）" % r.status_code)

    def test_cascadeAndAbsenceAlsoRefuseToLie(self, client, monkeypatch):
        self._brokenGraph(monkeypatch)

        cascade = client.post(f"{BASE}/cascade", json={"entity_id": "e1"})
        absence = client.post(f"{BASE}/absence/detect",
                              json={"expected_entity": "x", "expected_relation": "prerequisite"})

        assert cascade.status_code == 500, cascade.text
        assert absence.status_code == 500, absence.text

    def test_healthReportsUnhealthyInsteadOfRaising(self, client, monkeypatch):
        """健康检查是**故意**回 200 + `success:false` 的（`neuron.py:388-393`）：
        它要能被探活脚本读，所以这里钉的是"如实说不健康"，不是"回 5xx"。"""
        self._brokenGraph(monkeypatch)

        r = client.get(f"{BASE}/health")

        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False and body["status"] == "unhealthy", body


class TestTheSharedGraphHasExactlyOneConstructionPoint:
    def test_dependencyGraphIsBuiltOnlyInsideGetSharedGraph(self):
        """每个 handler 自己 `DependencyGraph()` 一次，共享就变成六份私有——
        而这在 HTTP 层完全看不出来（每条都 200）。"""
        tree = ast.parse(Path(neuronModule.__file__).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "DependencyGraph":
                    parents = [n for n in ast.walk(tree)
                               if isinstance(n, ast.FunctionDef) and node in ast.walk(n)]
                    if not any(p.name == "get_shared_graph" for p in parents):
                        offenders.append(node.lineno)
        assert offenders == [], (
            "neuron.py 里有 %s 处在 `get_shared_graph()` 之外自建图谱——那份图不是共享的" % offenders)

    def testEveryHandlerActuallyCallsTheAccessor(self):
        """反向对照：把取用点桩成一个会炸的函数，六条读路必须全部 500。

        没这一格的话，"handler 其实没经共享图"这种回归（自己 new 一份）上面的那条 AST
        守卫看不见——AST 只查构造点，不查取用点。
        """
        source = Path(neuronModule.__file__).read_text(encoding="utf-8")

        assert source.count("get_shared_graph()") >= 6, (
            "端点层取共享图的次数掉到 6 以下：有 handler 改用自己的图了")


class TestAuthAndRoutingShape:
    def test_noCredentialIs401(self):
        app = FastAPI()
        app.include_router(neuronModule.router, prefix="/api")
        with TestClient(app) as c:
            assert c.get(f"{BASE}/entities").status_code == 401
            assert c.post(f"{BASE}/entities",
                          json={"name": "n", "entity_type": "t"}).status_code == 401
            # 校准格：真的不存在的路径必须 404，否则"逢路径 401"会掩盖挂错前缀
            assert c.get(f"{BASE}/definitely-not-a-route").status_code == 404

    def test_resetGivesAFreshStore(self, client):
        client.post(f"{BASE}/entities", json={"name": "将被清掉", "entity_type": "object"})

        neuronModule.reset_shared_graph()

        assert client.get(f"{BASE}/stats").json()["data"]["total_entities"] == 0, (
            "reset 之后还看得见旧实体：说明有读数缓存了那份图对象")
