# -*- coding: utf-8 -*-
"""身份门只能有一份实现；两种凭证来源要叫两个名字

缺陷（§6-28 登记）：`api/auth.py:415` 与 `api/deps.py:38` 是**同名不同体**的
`get_current_user`，`get_optional_user` 同样两份（`auth.py:539` / `deps.py:81`）。
两份的差别不止实现，还差在**凭证来源策略**：auth 那一份只认 `Authorization: Bearer`
（`HTTPBearer`，84 个文件在用），deps 那份额外接受 `?access_token=`
（`BearerOrQuery`，21 个文件在用——`<img>`/`<audio>`/`<a download>` 资源标签发不出头）。

同名双实现在这个仓里造成两类实际故障：
1. `dependency_overrides[auth.get_current_user]` 对用 deps 那份的端点**静默不生效**
   ——本轮写 console/stats 测试时正好撞上：override 打了另一个对象，请求照旧 401，
   看起来像"守卫没咬住"，其实是替换没生效。这类假绿比红更危险。
2. 读代码时无法从名字判断这个端点接受哪种凭证。

修法（第 7 条先比后合）：身份推导（校验 → 401/None → `_user_identity`）在 `auth.py`
只留一份；两个凭证入口分别命名（严格版沿用 `get_current_user`，查询回退版叫
`get_current_userWithQueryToken`）；`deps.py` 的两个同名实现删除、改为再导出
——**保留 deps 旧名**是因为它的 21 个消费方与 3 个测试文件的导入路径不该被无谓搅动，
而真正要紧的是"只有一份实现"与"两个入口语义不同名"。

不合并成一份严格门是**故意的**：那会把 `?access_token=` 放行面从 21 个文件扩到 84 个
（token 进 URL 会落进访问日志/历史记录），属放宽安全面；反过来取消查询回退会打断
产物预览与下载。两种策略都合法，只是不许共用一个名字。

`verify_access_token` → `verify_token` 实测只 `return None` 从不抛（`auth.py:281/286`），
所以 deps 版本里包 `verify` 的 `except Exception` 是死码，合并时不搬（教义第 6 条：
不带冗余兜底）。
"""

import inspect
import typing

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api import deps as deps_mod


@pytest.fixture
def token():
    from neurova.api.auth import create_access_token

    return create_access_token({"sub": "alice", "neuser_id": "ne-alice"})


def _appFor(dependency):
    app = FastAPI()

    @app.get("/probe")
    async def probe(user: typing.Dict[str, typing.Any] = Depends(dependency)):
        return {"user_id": user.get("user_id"), "neuser_id": user.get("neuser_id")}

    @app.get("/probe-optional")
    async def probeOptional(user: typing.Optional[dict] = Depends(dependency)):
        return {"user": user and user.get("user_id")}

    return app


def _status(dep, *, header=None, query=None, optional=False):
    client = TestClient(_appFor(dep))
    path = "/probe-optional" if optional else "/probe"
    headers = {"Authorization": f"Bearer {header}"} if header else {}
    params = {"access_token": query} if query else {}
    resp = client.get(path, headers=headers, params=params)
    if resp.status_code == 422:  # optional 门返回 None 时端点自身仍 200
        return resp.status_code, None
    body = resp.json() if resp.status_code == 200 else None
    return resp.status_code, body


def test_identityDerivationIsSingleSource():
    """deps 里不得再有自己的身份推导实现。"""
    src = inspect.getsource(deps_mod)
    assert "def get_current_user(" not in src, "deps 仍保留第二份 get_current_user 实现"
    assert "def get_optional_user(" not in src, "deps 仍保留第二份 get_optional_user 实现"
    assert "verify_access_token" not in src, "deps 仍在自己校验 token（第二份校验口径）"


def test_overridesCannotMissTheTargetObject():
    """同一路径的依赖必须是**同一个函数对象**——否则 override 会打到空处静默失效。

    这是本缺陷最伤人的地方：它不会红，只会让守卫"看起来没咬住"。
    """
    assert deps_mod.get_current_user is auth_mod.get_current_userWithQueryToken, (
        "deps.get_current_user 不是 auth 那份的再导出，override 打错对象依旧会静默失效"
    )
    assert deps_mod.get_optional_user is auth_mod.get_optional_userWithQueryToken


def test_strictGateRejectsQueryToken(token):
    """严格版必须拒绝 ?access_token=（不许把放行面从 21 个文件扩到 84 个）。"""
    status, _ = _status(auth_mod.get_current_user, query=token)
    assert status == 401, f"严格版竟然接受了查询参数 token：{status}"
    okStatus, body = _status(auth_mod.get_current_user, header=token)
    assert okStatus == 200 and body["user_id"] == "alice", body


def test_queryCapableGateStillAcceptsQueryToken(token):
    """资源标签场景不许在合并中退化（`<img>` 等发不出 Authorization 头）。"""
    status, body = _status(deps_mod.get_current_user, query=token)
    assert status == 200, f"查询回退版不收 ?access_token= 了：{status}"
    assert body == {"user_id": "alice", "neuser_id": "ne-alice"}, body
    # 头优先：两者都在时用头里的凭证，不被查询参数覆盖成别的身份
    status2, body2 = _status(deps_mod.get_current_user, header=token, query="not-a-token")
    assert status2 == 200 and body2["user_id"] == "alice", (status2, body2)


def test_optionalGateSemanticsPreserved(token):
    """optional 门：无凭证 None、坏 token 仍 None（合并既不许变严也不许变松）。"""
    status, body = _status(deps_mod.get_optional_user, optional=True)
    assert (status, body) == (200, {"user": None}), (status, body)
    status, body = _status(deps_mod.get_optional_user, query=token, optional=True)
    assert body == {"user": "alice"}, body
    status, body = _status(deps_mod.get_optional_user, query="garbage", optional=True)
    assert body == {"user": None}, f"坏 token 被当成了已认证：{body}"


def test_invalidTokenStillRejectedOnBothEntries(token):
    """两条入口对"有凭证但无效"都必须 401，不许回落 default/None。"""
    for dep in (auth_mod.get_current_user, deps_mod.get_current_user):
        status, _ = _status(dep, header="tampered.token.value")
        assert status == 401, f"{dep.__name__} 对无效 token 返回 {status}"


def test_theMeEndpointIsAHandlerNotADependency():
    """`endpoints/auth.py:445` 还有个叫 get_current_user 的 **GET /me 处理器**。

    它不是依赖（形参里没有任何 `Depends` 凭证入参，也没人 `Depends()` 它），
    但同名会让人误读为第三份实现、甚至被拿去 override。本条把这个区分钉成事实：
    它是端点，签名只有 request。
    """
    from neurova.api.endpoints import auth as authEndpoints

    handler = authEndpoints.get_current_user
    params = list(inspect.signature(handler).parameters)
    assert params == ["request"], f"GET /me 处理器签名不再是纯 request（{params}）——" \
        "若它开始吃凭证入参，就与身份依赖同名冲突，必须改名"
    assert inspect.iscoroutinefunction(handler), "GET /me 不再是协程端点"
    src = inspect.getsource(authEndpoints)
    head = src.split("async def get_current_user")[0]
    assert '@router.get("/me"' in head, "GET /me 的路径声明离了这函数，本守卫需同步"
