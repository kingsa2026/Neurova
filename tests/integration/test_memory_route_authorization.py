"""内存端点授权接线（真 router + 真鉴权依赖 + 真 MemoryManager）

取证报告 `audit-reports/memory-isolation-2026-10-05.md` 的三条现行面，都出在端点
绕开了 manager 的收口：

- `PUT /{memory_id}` 调没有归属校验的 `update_memory`（`crud.py:331`）；
- `DELETE /{memory_id}` 无条件传 `forget(..., agent_wide=True)`（`crud.py:362`），
  把三层隔离的第 2、3 层显式关掉；
- `GET /{memory_id}` 既无鉴权依赖（同文件其余 10 个端点都有），又读
  `manager.storage.get()` —— 那个 `MemoryManager._storage` 实例全仓零写入方，
  所以这条"记忆详情"路由对任何人都恒 404。

装配口径：router、鉴权依赖、`get_memory_manager`、`MemoryManager` 全是生产实现。
只把 `neurova.api.app.get_app_state` 换成一个供出该 manager 的桩状态——不为绕过
装配点，而是不把整个 app 的启动与其单例/落库副作用拖进每条用例；被测面仍是端点本身。

身份口径 2026-10-08 换过一次（P3-12 C1）：原来经 `dependency_overrides` 注入返回位，
现在改签**生产同一个函数产出的真 JWT**。原因是写侧门挂在
`APIRouter(dependencies=[Depends(requireIdentityForMemoryFace)])` 上，它判的是**请求有没有
凭证**，不看被 override 的那个函数——override 只能替掉处理器级的身份解析，替不掉路由级
的凭证检查，于是旧夹具全部 401。换成真 token 反而把整条凭证链纳进覆盖范围。
（2026-10-26 点单甲后，这道门从"只管写"收成"读写都要凭证"，名字随之改。）
"""

import types
import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests.auth_headers import bearerHeaders

#: 真 JWT 的请求头；不带 headers 即匿名
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
    # APIError → 标准 JSON 信封的处理器也是生产装配的一部分（`_register_routes`
    # 里就调它）。不挂的话 `raise APIError.not_found(...)` 会作为异常冒出 500，
    # 断到的就不是端点的授权判定而是测试装配。
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    return TestClient(app)


def _createAsAlice(client) -> str:
    r = client.post("/api/v1/memory", json={"content": "ALICE-原内容", "auto_classify": False},
                    headers=ALICE_HDR)
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


class TestMemoryRouteAuthorization:
    def test_ownerReadsItsMemoryById(self, client):
        """GET /{id} 必须真能读到（现读零写入的 storage → 恒 404）"""
        memoryId = _createAsAlice(client)

        r = client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR)

        assert r.status_code == 200, f"归属者读自己的记忆详情应 200，实得 {r.status_code}: {r.text}"
        assert r.json()["data"]["content"] == "ALICE-原内容", r.text

    def test_otherUserCannotUpdate(self, client):
        memoryId = _createAsAlice(client)

        r = client.put(f"/api/v1/memory/{memoryId}", json={"content": "TAMPERED-by-bob"},
                       headers=BOB_HDR)

        assert r.status_code == 404, f"他人 PUT 应视同不存在，实得 {r.status_code}: {r.text}"
        r = client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR)
        assert r.json()["data"]["content"] == "ALICE-原内容"

    def test_anonymousCannotUpdate(self, client):
        """C1 后匿名写**根本进不到租户判定**：路由级写门先 401。

        原来是回落 default 租户再被归属校验拦成 404——两道门任一道塌了都只剩 404，
        现在两道门各自可核实：这条钉 401，`testEveryMemoryWriteRouteRejectsAnonymous` 钉覆盖面。
        """
        memoryId = _createAsAlice(client)

        r = client.put(f"/api/v1/memory/{memoryId}", json={"content": "TAMPERED-by-anon"})

        assert r.status_code == 401, f"匿名 PUT 应被写门拒绝，实得 {r.status_code}: {r.text}"
        r = client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR)
        assert r.json()["data"]["content"] == "ALICE-原内容"

    def test_otherUserCannotDelete(self, client):
        memoryId = _createAsAlice(client)

        r = client.delete(f"/api/v1/memory/{memoryId}", headers=BOB_HDR)

        assert r.status_code == 404, f"他人 DELETE 应视同不存在，实得 {r.status_code}: {r.text}"
        assert client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR).status_code == 200

    def test_anonymousCannotDelete(self, client):
        """`agent_wide=True` 把第 2、3 层关掉，于是匿名也能"遗忘"他人记忆"""
        memoryId = _createAsAlice(client)

        r = client.delete(f"/api/v1/memory/{memoryId}")

        assert r.status_code == 401, f"匿名 DELETE 应被写门拒绝，实得 {r.status_code}: {r.text}"
        assert client.get(f"/api/v1/memory/{memoryId}", headers=ALICE_HDR).status_code == 200


class TestMemoryIdentityIsSingleSource:
    """身份只有一个来源：端点用依赖给的用户，不再从请求头自己再解析一遍"""

    def test_tokenBypassHelperIsRetired(self):
        from neurova.api.endpoints.memory import base

        assert not hasattr(base, "_get_user_ids_from_token"), (
            "旁路仍在：它会与 get_current_user_or_default 各给一份答案"
        )

    def test_everyTenantScopedRouteResolvesUserThroughTheDependency(self):
        """判据取"这个端点会不会拿到租户数据"这个可核实的事实：
        处理器里出现 `get_memory_manager(` 的路由，身份必须来自依赖。
        （不写"全部路由都算"——`/emotion/types` 只回静态枚举，硬套依赖就成了
        无人消费的装饰参数。）

        口径 2026-10-26 放宽过一次**前提**（不是放宽闸）：管理通道
        `/management/{memory_id}` 的身份来自 `deps.require_admin()` 那条链上的**严格门**
        `get_current_user`，而不是本文件当初唯一认的 `get_current_user_or_default`。
        继续只认后者，就会把"取身份更严格"的那条路判成没鉴权。取源改为运行时现枚举
        的全部身份入口（`tests/auth_headers._identityEntryPoints`，仓内为此事的单点），
        入口再加一条时这里自动跟上。"严格到什么程度"由下一格单独钉。
        """
        import inspect

        from tests.auth_headers import _identityEntryPoints

        identityEntries = set(_identityEntryPoints())
        offenders = []
        for route in memoryRouter.routes:
            src = inspect.getsource(route.endpoint)
            if "get_memory_manager(" not in src:
                continue
            calls: typing.List[typing.Any] = []
            stack = list(getattr(route, "dependencies", []) or [])
            if getattr(route, "dependant", None) is not None:
                stack.extend(route.dependant.dependencies)
            while stack:
                dep = stack.pop()
                if getattr(dep, "call", None) is not None:
                    calls.append(dep.call)
                stack.extend(getattr(dep, "dependencies", []) or [])
            if not identityEntries.intersection(calls):
                offenders.append(f"{sorted(getattr(route, 'methods', []) or [])} {route.path}")

        assert offenders == [], "以下取租户数据的内存端点没有鉴权依赖：\n" + "\n".join(sorted(offenders))

    def test_managementRoutesResolveIdentityThroughTheStrictGate(self):
        """反向钉住上一条放宽的方向：管理通道必须取**严格门**那份身份。

        上一格把"认哪一个函数"改成"认入口集合"，这一格保证集合里的宽松那份
        （可回退 `?access_token=` 的那条策略）不能顶替严格那份——跨用户特权面
        不该有一条能从 URL 参数带身份的入口。
        """
        management = [
            r for r in memoryRouter.routes if r.path == "/management/{memory_id}"
        ]

        assert management, "管理通道路由不在册（本格失去被测对象即红）"
        offenders = []
        for route in management:
            calls = []
            stack = list(getattr(route, "dependencies", []) or [])
            if getattr(route, "dependant", None) is not None:
                stack.append(route.dependant)
            while stack:
                dep = stack.pop()
                if getattr(dep, "call", None) is not None:
                    calls.append(dep.call)
                stack.extend(getattr(dep, "dependencies", []) or [])
            if auth_mod.get_current_user not in calls:
                offenders.append(f"{sorted(getattr(route, 'methods', []) or [])}")

        assert offenders == [], f"以下管理通道端点没走严格身份门：{offenders}"
