"""角色门的身份源必须是严格门本体，而不是可回退查询参数那份（§6-54）。

C1 收口记忆面时撞出来的那一格（台账 §6-54）：`deps.require_role()` 内部
`Depends(get_current_user)` 指的是 `deps` 那份**再导出**——
`auth.get_currentUserWithQueryToken`，即"无 Authorization 头时回退 `?access_token=`"。
于是**每一个角色门**（`require_admin()` / `require_role(...)`，全仓 21 个文件在用）
都默认接受了 URL 里的凭证。

这不是"多一条便利入口"，是**特权面的凭证暴露面**：`?access_token=` 会落进
反向代理与 uvicorn 的访问日志、浏览器历史、Referer，以及任何被截图/粘出的链接。
普通用户把自己的 token 串贴进工单，泄露的只是自己；**管理员**的 token 串贴出去，
泄露的是全站管理权。放行面按端点显式选择这条口径（`deps.py:22-25` 写着）在
`generation`/`console_files`/`workspace_files` 这些**资源标签**端点上是成立的，
但角色门从来不是资源标签端点——它落在 `api/index.ts` 的统一 Authorization 头上。

两种凭证策略**不并成一份**（那是 §6-54 里 A/B 两个处置的分别），本批只做一件事：
把角色门那一侧的取源改成严格门本体。因此判据必须同时钉住"收口"与"不许过界"：

- 收口：`?access_token=<管理员 token>` 打角色门端点 → **401**（不给特权），
  同一枚 token 走 `Authorization` 头 → 照常 200；
- 不许过界：资源标签面（`deps.get_current_user` 那份直用）带 `?access_token=` **仍须**
  放行——把它一起打死就是 `deps.py:22-25` 点名警告过的"把查询凭证推广到 84 个
  严格端点"的反向错误。
"""

import os
import typing

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_role_gate_0123456789")

from neurova.api import auth as auth_mod
from neurova.api import deps as deps_mod

ADMIN_TOKEN = auth_mod.create_access_token(
    {"sub": "root-admin", "username": "root-admin", "role": "admin", "neuser_id": "root-admin"}
)
USER_TOKEN = auth_mod.create_access_token(
    {"sub": "plain-user", "username": "plain-user", "role": "user", "neuser_id": "plain-user"}
)


@pytest.fixture
def app():
    """一条角色门端点 + 一条资源标签端点，两条都挂生产实现的那两道依赖。"""
    app = FastAPI()

    @app.get("/admin-only")
    async def adminOnly(_admin: typing.Dict[str, typing.Any] = Depends(deps_mod.require_admin())):
        return {"ok": True}

    @app.get("/asset")
    async def asset(user: typing.Dict[str, typing.Any] = Depends(deps_mod.get_current_user)):
        return {"ok": True, "as": user.get("user_id")}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestRoleGateTakesIdentityFromStrictSource:
    def testQueryTokenDoesNotGrantAdmin(self, client):
        """管理员 token 出现在查询串上必须被拒——特权不走 URL。"""
        resp = client.get("/admin-only", params={"access_token": ADMIN_TOKEN})
        assert resp.status_code == 401, (
            f"`?access_token=` 拿到了角色门：{resp.status_code} {resp.text[:120]} "
            "（token 进 URL 会落进访问日志/浏览器历史/Referer，管理员的串等于全站管理权）"
        )

    def testHeaderStillGrantsAdmin(self, client):
        """收口不许把正路一起挡掉：同一枚 token 走 Authorization 头照常通。"""
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert resp.status_code == 200, f"管理员带头请求被拒：{resp.status_code} {resp.text[:120]}"

    def testNonAdminHeaderIs403Not401(self, client):
        """身份成立、角色不足 → 403。这条钉住"收口改的是凭证来源，不是角色判定"。"""
        resp = client.get("/admin-only", headers={"Authorization": f"Bearer {USER_TOKEN}"})
        assert resp.status_code == 403, f"非管理员应 403，实得 {resp.status_code} {resp.text[:120]}"

    def testAnonymousIs401(self, client):
        resp = client.get("/admin-only")
        assert resp.status_code == 401, f"匿名应 401，实得 {resp.status_code}"


class TestResourceTagSurfaceUntouched:
    def testAssetEndpointStillAcceptsQueryToken(self, client):
        """反向钉：资源标签面**必须**继续吃 `?access_token=`。

        `<img>`/`<a download>` 发不出 Authorization 头，产物预览与下载只能走查询参数
        （`NeurUI/src/utils/genFiles.ts:6-8` 记的就是这个契约）。把这条一起收紧，
        就是 `deps.py:22-25` 点名警告的反向错误——所以要单独钉住，不许"顺手统一"。
        """
        resp = client.get("/asset", params={"access_token": USER_TOKEN})
        assert resp.status_code == 200, (
            f"资源标签面被一起打死：{resp.status_code} {resp.text[:120]}"
        )

    def testAssetEndpointHeaderPathWorksToo(self, client):
        resp = client.get("/asset", headers={"Authorization": f"Bearer {USER_TOKEN}"})
        assert resp.status_code == 200, resp.text


class TestSingleSourceOfIdentityDerivation:
    def testRoleGateResolvesThroughTheStrictDependency(self):
        """判据取**对象同一性**，不比函数名。

        本仓栽过两次：同名不同体的两份 `get_current_user`，以及
        `dependency_overrides` 打到另一份上静默失效。名字比对会放过"改叫别的名字
        但仍是查询参数那份"，对象同一性不会。
        """
        inner = deps_mod.require_role("admin")
        calls = []
        # `fastapi.Depends` 是**函数**（返回 fastapi.params.Depends 实例），
        # isinstance 的第二个参数必须是类型——判据取 params 层那个类，不取门面函数。
        import inspect

        from fastapi.params import Depends as DependsMarker

        for p in inspect.signature(inner).parameters.values():
            dep = p.default
            if isinstance(dep, DependsMarker):
                # 本仓 FastAPI 0.142.2 的字段名是 `dependency`（不是 `depend`），
                # 取错字段会让判据恒 AttributeError 而非恒绿——两种都要防。
                calls.append(dep.dependency)
        assert calls, "require_role 的 check_role 没有 Depends 形参，判据前提变了"
        assert calls[0] is auth_mod.get_current_user, (
            "角色门的身份源不是严格门本体——"
            f"实为 {calls[0].__module__}.{calls[0].__name__}；"
            "若那是 WithQueryToken，则每个角色门都默认接受 URL 凭证"
        )

    def testRoleGatePredicateStillHasOneImplementation(self):
        """角色比较不许被复制：admin 分支在 `agent_access` 只有一份。"""
        import inspect

        from neurova.api import agent_access

        assert inspect.getsource(agent_access.can_access_agent).count('== "admin"') == 1, (
            "admin 口径被复制成多份——§6-60 想接共享谓词时就没有唯一去处了"
        )
