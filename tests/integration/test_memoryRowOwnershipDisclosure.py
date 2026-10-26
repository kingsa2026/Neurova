"""记忆列表面逐条披露归属：`owned` 与三层隔离出自同一条判定（点单「丙」）

缺陷现场（2026-10-26 用户贴的控制台读数）：
`GET /api/v1/memory/merged_mem_000010_2` → 404。该行在盘上存在，归属三元组是
`('default', 'ne-alice', 'alice')`；列表面能看见它，详情面看不见它。

根因不是"记录丢了"，是**同一页两套口径**：
- 列表面（`GET /memory`、`/hot`、`/crystallized`）传 `agent_wide=True`，把三层隔离的
  第 2、3 层显式关掉，于是本 agent 下**所有用户域**的行都进了表格；
- 详情/改/删走 `agent_wide=False`，他人作用域「视同不存在」（P1-6，既有口径，
  由 `tests/integration/test_memory_route_authorization.py` 钉死，本批不动它）。
表格把服务端注定要拒绝的行照常摆出「打开/编辑/遗忘/删除」，用户点下去必 404。

处置形态（用户在三态票里点的丙，不是甲也不是乙）：详情面保持"视同不存在"，
列表面**如实说这一行动得了吗** —— 每条带一个布尔 `owned`，前端据此禁用动作并标注。
所以 `owned` 的取源必须是**服务端判定归属的那一条规则本身**，不能是第二份猜法：
本批把原先手抄在六处的归属比较收口成 `MemoryManager.isOwnedByRequestScope()` 一处，
投影与闸门同调它。两侧从此不可能分家。

`owned` 是布尔，不是三元组：把 `neuser_id`/`user_id` 抄到线上是给"按 id 匿名读任意记录"
再开一个入口（P1-6 当初正是为此选择"视同不存在"）。故本文件有一格反向钉住泄漏面。

装配口径与 `test_memory_route_authorization.py` 一致：router、鉴权依赖、
`get_memory_manager`、`MemoryManager` 全是生产实现，只把 `get_app_state` 换成供出该
manager 的桩；身份用生产 `create_access_token()` 签的真 JWT，不用 `dependency_overrides`。
"""

import types
import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests.auth_headers import bearerHeaders

ALICE_HDR = bearerHeaders("alice")
BOB_HDR = bearerHeaders("bob")


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


@pytest.fixture
def client(manager, monkeypatch):
    agent = types.SimpleNamespace(memory_manager=manager)
    state = types.SimpleNamespace(agents={"agent_a": agent}, get_agent=lambda *a, **k: agent)
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: state)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    return TestClient(app, headers=BOB_HDR)


def _createAsAlice(client) -> str:
    r = client.post(
        "/api/v1/memory",
        json={"content": "ALICE-的行", "auto_classify": False},
        headers=ALICE_HDR,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _createAsBob(client, **extra) -> str:
    r = client.post(
        "/api/v1/memory",
        json={"content": "BOB-的行", "auto_classify": False, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _rows(client, path: str = "/api/v1/memory", **params) -> typing.Dict[str, dict]:
    """取列表信封里的行，按 id 索引；顺带把整个响应体留作泄漏检查用。"""
    r = client.get(path, params={"limit": 50, **params})
    assert r.status_code == 200, r.text
    return {m["id"]: m for m in r.json()["data"]["memories"]}


class TestMemoryListDisclosesRowOwnership:
    def test_foreignRowIsMarkedNotOwned(self, client):
        """别人作用域的行：列表面照常给，但必须说「这条你动不了」"""
        memoryId = _createAsAlice(client)

        rows = _rows(client)

        assert memoryId in rows, f"列表面本就能跨作用域看见该行，实测缺席：{list(rows)}"
        assert rows[memoryId].get("owned") is False, rows[memoryId]

    def test_ownRowIsMarkedOwned(self, client):
        """反向控制：同一次调用里自己的行必须 True，否则 owned 是恒假的装饰字段"""
        foreignId = _createAsAlice(client)
        ownId = _createAsBob(client)

        rows = _rows(client)

        assert rows[ownId]["owned"] is True, rows[ownId]
        assert rows[foreignId]["owned"] is False, rows[foreignId]

    def test_hotAndCrystallizedCarryTheSameSignal(self, client, manager):
        """同一张表格还有两个数据源，漏一个就是本页两套口径的复现。

        新建行的温度是 65（`remember` 落点），高温门默认 80，所以高温那条走生产
        记账口 `creditRecallHits()`（每次 +10，封顶 100）抬进高温集 —— 不手工改
        私有字段；固化那条由 `is_crystallized=True` 落 `lifecycle_stage=crystallized`。
        """
        aliceHot = _createAsAlice(client)
        assert manager.creditRecallHits([aliceHot]) == 1, "抬温没生效，高温腿白测"
        assert manager.creditRecallHits([aliceHot]) == 1
        aliceCrystallized = client.post(
            "/api/v1/memory",
            json={
                "content": "ALICE-固化",
                "auto_classify": False,
                "is_crystallized": True,
            },
            headers=ALICE_HDR,
        ).json()["data"]["memory_id"]

        hotRows = _rows(client, "/api/v1/memory/hot", limit=50)
        crystalRows = _rows(client, "/api/v1/memory/crystallized", limit=50)

        assert aliceHot in hotRows, f"高温腿没带出该行：{list(hotRows)}"
        assert hotRows[aliceHot]["owned"] is False, hotRows[aliceHot]
        assert aliceCrystallized in crystalRows, f"固化腿没带出该行：{list(crystalRows)}"
        assert crystalRows[aliceCrystallized]["owned"] is False, crystalRows[aliceCrystallized]

    def test_projectionDoesNotLeakOwnerIdentity(self, client):
        """披露的是「能不能动」，不是「这是谁的」：三元组不得上线上。"""
        memoryId = _createAsAlice(client)

        body = client.get("/api/v1/memory", params={"limit": 50}).text

        assert "neuser_id" not in body, body
        row = _rows(client)[memoryId]
        assert "user_id" not in row, row

    def test_detailRouteStillTreatsForeignRowAsAbsent(self, client):
        """口径不变的反向钉：本批只加披露，不得顺手放宽详情面（P1-6）。"""
        memoryId = _createAsAlice(client)

        r = client.get(f"/api/v1/memory/{memoryId}")

        assert r.status_code == 404, f"他人仍应视同不存在，实得 {r.status_code}: {r.text}"
        assert (
            client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR).status_code == 200
        ), "归属者读自己的详情不得被本批打断"


class TestOwnershipRuleIsSingleSource:
    """`owned` 与闸门同一条规则：归属比较在 manager 里只剩一处定义。

    六处手抄是本批建档时的已知命中点（当下限钉住，掉出即红）：两处基集
    `_scoped_memories`/`_agent_memories`、语义召回入口过滤 `_semantic_recall`、
    三个读写闸门 `get_memory`/`update_memory`/`forget`。
    刻意**不在**这份名单里的是 `_merge_loaded_memory`/`_already_loaded`：它们问的是
    「同 id 两行谁占内存槽」「这篇是否已装载」，不含 agent 轴，不是访问闸门。
    """

    GATE_METHODS = (
        "_scoped_memories",
        "_agent_memories",
        "_semantic_recall",
        "get_memory",
        "update_memory",
        "forget",
    )

    def _body(self, methodName: str) -> str:
        import inspect

        fn = getattr(MemoryManager, methodName)
        return inspect.getsource(fn)

    def _scopeComparisons(self, methodName: str) -> typing.List[str]:
        """该方法体里手抄的归属比较（`mem.neuser_id == self._eff_neuser_id()` 那一形）。

        只取 `Compare` 节点：写侧构造 `neuser_id=self._eff_neuser_id()`、拒绝日志里
        打印生效作用域都不算重新判定，硬按词筛会把正常代码一起钉红。
        """
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(self._body(methodName)))
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            if attrs & {"_eff_neuser_id", "_eff_user_id", "_agent_id"} or attrs & {
                "neuser_id",
                "user_id",
            }:
                hits.append(getattr(node, "lineno", 0))
        return hits

    def test_gateMethodsDelegateInsteadOfReimplementing(self):
        offenders = {name: self._scopeComparisons(name) for name in self.GATE_METHODS}
        offenders = {name: hits for name, hits in offenders.items() if hits}

        assert offenders == {}, (
            "以下访问闸门又自己抄了一遍归属比较，列表面披露的 owned 会与它们分家："
            f"{offenders}"
        )

    def test_gateMethodsAllCallTheSinglePredicate(self):
        missing = [
            name for name in self.GATE_METHODS if "isOwnedByRequestScope(" not in self._body(name)
        ]

        assert missing == [], f"以下访问闸门没走单源归属判定：{missing}"

    def test_httpProjectionReadsOwnershipFromTheSamePredicate(self):
        """端点侧不许再猜一遍「这行是谁的」：投影要么带 `owned=` 问 manager，
        要么走 `memories_to_dicts` 单点；裸调 `memory_to_dict` 就是第二份判定。"""
        import re
        from pathlib import Path

        import neurova.api.endpoints.memory.base as memory_base

        pkg = Path(memory_base.__file__).parent
        offenders = []
        for py in sorted(pkg.glob("*.py")):
            if py.name == "base.py":
                continue  # 定义与投影单点本身
            for call in re.findall(r"memory_to_dict\(([^)]*)\)", py.read_text(encoding="utf-8")):
                if "owned=" not in call:
                    offenders.append(f"{py.name}: memory_to_dict({call.strip()})")

        assert offenders == [], "以下记忆投影没有从 manager 取归属，它是在自己判第二遍：\n" + "\n".join(
            offenders
        )

    def test_listEndpointsUseTheSingleProjector(self):
        """`/memory`、`/hot`、`/crystallized`、`/emotion/{type}` 四条列表腿共用一个投影口。"""
        import inspect

        from neurova.api.endpoints.memory import crud, emotion

        offenders = [
            mod.__name__
            for mod in (crud, emotion)
            if "memories_to_dicts(" not in inspect.getsource(mod)
        ]

        assert offenders == [], f"以下模块的列表端点没接上单一投影口：{offenders}"
