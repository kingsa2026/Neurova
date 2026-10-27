"""管理通道（带 role 门的 agent-wide 显式端点）——读／改／删跨用户作用域的那条正路

用户裁定（2026-10-26，承 §6-425 那张需人裁票）：管理员要能跨用户操作记忆，
正当落点是 `crud.py` 里 DELETE 那段注释早已预留的**带 role 门的显式端点**，
而不是把三层隔离改宽（那是 §6 禁的平行口径回退），也不是把列表面一起收窄
（那是乙案，代价是跨用户记忆视图消失）。

于是形状定了：
- 常规 `GET/PUT/DELETE /memory/{memory_id}` **一字不动**，仍按三层隔离对他人行"视同不存在"
  （P1-6，`test_memory_route_authorization.py` 钉着）。管理员走这条也一样 404——
  门只开在新通道上，老门没被放宽，本文件有一格反向钉这件事。
- 新增 `GET/PUT/DELETE /memory/management/{memory_id}`，挂 `deps.require_admin()`，
  经门之后按 `agent_wide=True` 调**同一份** manager 动词。
- 列表面逐条给的 `owned` 从此**随请求方可用的通道**判：admin 动得了（管理通道），
  普通用户动不了（他人行）。这条不是新判据，是把同一个 manager 谓词按调用方权限
  多传一个参数——所以本文件要证"门"与"披露"两侧同源（同一个身份，两条路读数一致）。

装配口径与同目录两份判据一致：真 router、真鉴权依赖、真 `get_memory_manager`、真
`MemoryManager`；只把 `get_app_state` 换成供出该 manager 的桩（不为绕装配点，而是不把
整个 app 的启动与落库副作用拖进每条用例）。身份用生产 `create_access_token()` 签的真
JWT——`role` 走 JWT 声明（`auth.py:_user_identity` 取 `payload["role"]`，缺省落 "user"）。
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

#: 行属主（作用域 alice/alice，角色 user）
OWNER_HDR = bearerHeaders("alice")
#: 同 agent 下的普通用户（既不是属主也不是管理员）
PLAIN_HDR = bearerHeaders("bob")
#: 管理员，但不是这些行的属主（作用域 mallory/mallory）
ADMIN_HDR = bearerHeaders("mallory", role="admin")

MANAGEMENT = "/api/v1/memory/management"


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
    return TestClient(app)


def _createAsAlice(client) -> str:
    r = client.post(
        "/api/v1/memory",
        json={"content": "ALICE-原内容", "auto_classify": False},
        headers=OWNER_HDR,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _roleGateCallsOn(route) -> typing.List[str]:
    """该路由依赖链里出现过的角色门工厂产物（`require_role` 的内层函数）。"""
    found = []
    stack = list(getattr(route, "dependencies", []) or [])
    if getattr(route, "dependant", None) is not None:
        stack.append(route.dependant)
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            found.append(getattr(call, "__qualname__", ""))
            if getattr(call, "__closure__", None):
                import inspect

                names = inspect.getclosurevars(call).nonlocals
                if "required_role" in names:
                    found.append(f"required_role={names['required_role']}")
        stack.extend(getattr(dep, "dependencies", []) or [])
    return found


class TestManagementChannelIsRoleGated:
    def test_anonymousIsRejectedByCredentialGate(self, client):
        """匿名连门都进不来（strict gate 先 401，不落到归属判定）"""
        memoryId = _createAsAlice(client)

        r = client.get(f"{MANAGEMENT}/{memoryId}")

        assert r.status_code == 401, f"匿名应被凭证门拒绝，实得 {r.status_code}: {r.text}"

    def test_plainUserGets403Not404(self, client):
        """普通用户必须是 403「角色不够」，不能是 404「查无此行」——
        回落 404 就是把特权面伪装成不存在，也丢掉了"这条通道存在"这件事本身。"""
        memoryId = _createAsAlice(client)

        r = client.get(f"{MANAGEMENT}/{memoryId}", headers=PLAIN_HDR)

        assert r.status_code == 403, f"非管理员应 403，实得 {r.status_code}: {r.text}"

    def test_adminReadsForeignRowContent(self, client):
        memoryId = _createAsAlice(client)

        r = client.get(f"{MANAGEMENT}/{memoryId}", headers=ADMIN_HDR)

        assert r.status_code == 200, f"管理员跨用户读应 200，实得 {r.status_code}: {r.text}"
        assert r.json()["data"]["content"] == "ALICE-原内容", r.text
        assert r.json()["data"]["owned"] is True, r.text

    def test_adminEditsForeignRowAndOwnerSeesIt(self, client):
        """改要**真落到属主读得见的同一行**：只回 200 不算闭环。"""
        memoryId = _createAsAlice(client)

        r = client.put(
            f"{MANAGEMENT}/{memoryId}",
            json={"content": "ADMIN-改过的内容"},
            headers=ADMIN_HDR,
        )
        assert r.status_code == 200, f"管理员跨用户改应 200，实得 {r.status_code}: {r.text}"

        back = client.get(f"/api/v1/memory/{memoryId}", headers=OWNER_HDR)
        assert back.status_code == 200, back.text
        assert back.json()["data"]["content"] == "ADMIN-改过的内容", back.text

    def test_adminDeletesForeignRow(self, client):
        """删要**真落到那一行**：只回 200 不算闭环。

        落地形态是 `forget(soft=True)` 的软遗忘（`lifecycle_stage → forgotten`），
        行仍按 id 读得到——这是既有 DELETE 端点的语义，本批没改它，所以判据读的是
        那一行真的进入了 forgotten 阶段，而不是"读不到了"。
        """
        memoryId = _createAsAlice(client)

        r = client.delete(f"{MANAGEMENT}/{memoryId}", headers=ADMIN_HDR)

        assert r.status_code == 200, f"管理员跨用户删应 200，实得 {r.status_code}: {r.text}"

        back = client.get(f"{MANAGEMENT}/{memoryId}", headers=ADMIN_HDR)
        assert back.status_code == 200, back.text
        assert back.json()["data"]["lifecycle_stage"] == "forgotten", back.text

    def test_plainUserCannotDeleteViaManagement(self, client):
        memoryId = _createAsAlice(client)

        r = client.delete(f"{MANAGEMENT}/{memoryId}", headers=PLAIN_HDR)

        assert r.status_code == 403, f"非管理员删管理通道应 403，实得 {r.status_code}: {r.text}"
        back = client.get(f"/api/v1/memory/{memoryId}", headers=OWNER_HDR)
        assert back.json()["data"]["lifecycle_stage"] != "forgotten", back.text

    def test_plainUserStillEditsNothing(self, client):
        memoryId = _createAsAlice(client)

        r = client.put(
            f"{MANAGEMENT}/{memoryId}", json={"content": "TAMPERED-by-bob"}, headers=PLAIN_HDR
        )
        assert r.status_code == 403, f"非管理员写管理通道应 403，实得 {r.status_code}: {r.text}"

        back = client.get(f"/api/v1/memory/{memoryId}", headers=OWNER_HDR)
        assert back.json()["data"]["content"] == "ALICE-原内容", back.text


class TestRegularChannelIsNotWidened:
    """反向控制：新通道开起来的同时，老通道一条都没被放宽。"""

    def test_adminOnRegularRouteIsStillTreatedAsAbsent(self, client):
        """管理员走常规 `GET /{id}` 照样 404——特权只在新通道上。

        这一格是本批的护栏：如果实现图省事把 `get_memory` 的默认口径改成 agent-wide，
        或把 role 门挂到整个 router 上，这条立刻红。
        """
        memoryId = _createAsAlice(client)

        r = client.get(f"/api/v1/memory/{memoryId}", headers=ADMIN_HDR)

        assert r.status_code == 404, f"管理员在常规路仍应视同不存在，实得 {r.status_code}"
        assert client.get(
            f"/api/v1/memory/{memoryId}", headers=OWNER_HDR
        ).status_code == 200

    def test_ownerKeepsUsingRegularRoutes(self, client):
        memoryId = _createAsAlice(client)

        assert client.get(f"/api/v1/memory/{memoryId}", headers=OWNER_HDR).status_code == 200
        r = client.put(
            f"/api/v1/memory/{memoryId}", json={"content": "ALICE-自己改"}, headers=OWNER_HDR
        )
        assert r.status_code == 200, r.text


class TestDisclosureMatchesTheGate:
    """列表面 `owned` 的取源与门一致：同一个人看见的可动性＝他真动得了的集合。"""

    def test_foreignRowIsNotOwnedForPlainUserButOwnedForAdmin(self, client):
        memoryId = _createAsAlice(client)

        def ownedAs(headers):
            rows = client.get(
                "/api/v1/memory", params={"limit": 50}, headers=headers
            ).json()["data"]["memories"]
            return next(r["owned"] for r in rows if r["id"] == memoryId)

        assert ownedAs(PLAIN_HDR) is False, "普通用户动不了的行必须披露 false"
        assert ownedAs(ADMIN_HDR) is True, "管理员经管理通道动得了，却披露 false＝页面白禁用"
        assert ownedAs(OWNER_HDR) is True


class TestChannelIsOneImplementationBehindOneGate:
    """新通道是"同一份实现多一道门"，不是第二份读写实现。"""

    def testManagementRoutesExistAndCarryTheRoleGate(self):
        management = [r for r in memoryRouter.routes if r.path == "/management/{memory_id}"]

        assert {m for r in management for m in r.methods} >= {"GET", "PUT", "DELETE"}, (
            f"管理通道路由不齐：{[(sorted(r.methods), r.path) for r in management]}"
        )
        for route in management:
            gates = _roleGateCallsOn(route)
            assert any(q.endswith("require_role.<locals>.check_role") for q in gates), (
                f"{sorted(route.methods)} {route.path} 没挂 require_role 产出的角色门：{gates}"
            )
            assert "required_role=admin" in gates, f"角色门必须要求 admin：{gates}"

    def testRegularRoutesDoNotCarryTheRoleGate(self):
        offenders = []
        for route in memoryRouter.routes:
            if route.path != "/{memory_id}":
                continue
            if any(q.endswith("require_role.<locals>.check_role") for q in _roleGateCallsOn(route)):
                offenders.append(f"{sorted(route.methods)} {route.path}")

        assert offenders == [], f"常规路被挂上角色门＝把老通道改成特权：{offenders}"

    def testManagerVerbsAreCalledFromOnePlaceEach(self):
        """`get_memory`／`update_memory`／`forget` 在 crud.py 里各只出现一次——
        常规路与管理路都调同一份内部实现，否则就是教义第 7 条禁的并存各调各的。"""
        import inspect
        import re

        from neurova.api.endpoints.memory import crud

        src = inspect.getsource(crud)
        counts = {
            verb: len(re.findall(rf"manager\.{verb}\(", src))
            for verb in ("get_memory", "update_memory", "forget")
        }

        offenders = {verb: n for verb, n in counts.items() if n != 1}

        assert offenders == {}, f"以下 manager 动词在端点里被调了多份：{offenders}"
