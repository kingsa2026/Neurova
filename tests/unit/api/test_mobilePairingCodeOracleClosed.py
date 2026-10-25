"""配对码不是公开标识：按码回 200/404 的那两个口必须关成不可区分（§6-172 批 28，裁定乙）。

来历：`docs/s08_route_auth_baseline_2026-09-11.txt:787` 那一节 `router_deps=[]`，
逐条数下来七个 HTTP 口里只有 `POST /pairing/confirm` 是**设计上**给手机用的（手机没有 JWT）。
剩下两个按码回话的口一直是开的：

- `GET /pairing/qrcode/{code}` —— 认码回图、不认回 404；
- `GET /pairing/status/{code}` —— 认码回 `pending/confirmed/expired` 与设备名、不认回 404。

6 位码只有 10^6 个取值，`_generate_pairing_code` 的 docstring 自己写着它是**唯一认证凭据**
（P3-18 为此换成 CSPRNG）。一个不带凭证、按码给不同状态的口，就是一台**枚举预言机**：
探到一个存在的码之后直接 `confirm` 它，设备就挂到别人账号名下（`confirm` 有每 IP 限流，
这两个口没有）。所以这不是"少写一个 Depends"，是凭据校验面被旁路。

处置按裁定乙：两个口各挂路由级 `dependencies=[Depends(_get_current_user_id)]`——
**不改签名**（改了 handler 直接调用面与既有判据一起遭殃），`confirm` 的公开面原样留着。
`<img>` 发不出 Authorization 头，所以取图走 blob（渠道扫码那形已经是这么做 base64 的）。

判据：
1. 未带凭证时，两个口对**存在码**与**不存在码**回同一状态、同一响应（不可区分＝预言机关）；
2. 带凭证时两个口照常出图/回状态（防把门焊死、把功能一起杀掉）；
3. `confirm` 仍公开且**每 IP 限流仍在**（它是手机那一侧唯一该有的公开口）；
4. 自数面（教义第 5 条的常驻形态）：清单由路由表自己枚举，除 confirm/ws 外**每一条**都得有门——
   不靠人抄一张"该有门的表"（本卷记过：手抄登记表只审已登记的，漏项恒绿零红）；
5. 反空转：探测器对"门被摘掉"的复活样本必须点名。
"""
import inspect
import os

import pytest
from fastapi import FastAPI
from fastapi.params import Depends as DependsMarker
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_oracle_01234567")

from neurova.api.endpoints import mobile_pairing as MP
from neurova.tunnel import protocol

PREFIX = "/api/v1/mobile"
#: 手机侧该有的公开口（它们拿不到 JWT）：确认配对、扫码换地址、接入凭证续签。
#: S1b 新增的两条按同口径登记——公开的前提是**各自有限流**，见
#: `TestEveryCodeSpeakingRouteIsGated.test_every_public_door_keeps_its_own_rate_limiter`。
PUBLIC_BY_DESIGN = {"/pairing/confirm", "/pairing/resolve", "/pairing/refresh"}


def _mount(overrideIdentity: bool):
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    if overrideIdentity:
        app.dependency_overrides[MP._get_current_user_id] = lambda: "kai"
    return app


@pytest.fixture()
def anon():
    """没挂身份桩的 app：调用方不带任何凭证，读的就是外部人真能读到的那一面。"""
    MP._pairing_codes.clear()
    MP._pairing_codes["123456"] = {
        "code": "123456", "ref": "r" * protocol.PAIRING_REF_LENGTH,
        "pairing_id": "pair-oracle", "user_id": "kai", "device_name": "已配设备",
        "status": "pending", "created_at": 0, "expires_at": 2 ** 31,
    }
    with TestClient(_mount(False), base_url="http://testserver",
                    raise_server_exceptions=False) as c:
        yield c
    MP._pairing_codes.clear()


@pytest.fixture()
def authed():
    MP._pairing_codes.clear()
    MP._pairing_codes["123456"] = {
        "code": "123456", "ref": "r" * protocol.PAIRING_REF_LENGTH,
        "pairing_id": "pair-oracle", "user_id": "kai", "device_name": "已配设备",
        "status": "pending", "created_at": 0, "expires_at": 2 ** 31,
    }
    app = _mount(True)
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()


def _indistinguishable(anon, pathExists: str, pathMissing: str) -> str:
    """两个不同答案的码给出**完全相同**的回话 ⇒ 外部人读不到"这个码存在吗"。"""
    a, b = anon.get(pathExists), anon.get(pathMissing)
    assert a.status_code == b.status_code, (
        f"存在码回 {a.status_code}、不存在码回 {b.status_code}——按码可区分＝枚举预言机还开着")
    assert a.status_code in (401, 403), (
        f"未带凭证却回 {a.status_code}（且与不存在码同形）：门根本没上或上了个假门")
    assert a.content == b.content, (
        f"状态码相同但响应体不同（{a.content!r} ↔ {b.content!r}）：细节仍在漏码存在性")
    return f"同为 {a.status_code}"


class TestCodeOracleIsClosed:
    def test_qrcode_endpoint_does_not_confirm_code_existence(self, anon):
        _indistinguishable(anon, f"{PREFIX}/pairing/qrcode/123456",
                           f"{PREFIX}/pairing/qrcode/000000")

    def test_status_endpoint_does_not_confirm_code_existence(self, anon):
        _indistinguishable(anon, f"{PREFIX}/pairing/status/123456",
                           f"{PREFIX}/pairing/status/000000")
        assert "已配设备" not in anon.get(f"{PREFIX}/pairing/status/123456").text, (
            "设备名被回给了匿名调用方——门上了却还在漏信息")

    def test_authenticated_caller_still_gets_the_image_and_the_status(self, authed):
        """正向格：门是为了关预言机，不是为了杀功能。"""
        img = authed.get(f"{PREFIX}/pairing/qrcode/123456")
        assert img.status_code == 200 and img.content[:4] == b"\x89PNG", (
            f"带凭证反而取不到图：{img.status_code} {img.headers.get('content-type')}")
        status = authed.get(f"{PREFIX}/pairing/status/123456")
        assert status.status_code == 200 and status.json()["status"] == "pending", (
            f"带凭证读不到状态：{status.status_code} {status.text[:120]}")


def _gateOf(route):
    """这一条路由的"门"：路由级 dependencies 与签名里的 Depends 都算（两形都会出现在真码里）。"""
    for d in (getattr(route, "dependencies", None) or []):
        if getattr(d, "dependency", None) is MP._get_current_user_id:
            return "route-level"
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return None
    try:
        sig = inspect.signature(endpoint)
    except (TypeError, ValueError):
        return None
    for param in sig.parameters.values():
        if isinstance(param.default, DependsMarker) \
                and getattr(param.default, "dependency", None) is MP._get_current_user_id:
            return "signature"
    return None


def _isWs(route) -> bool:
    """WS 路由的类名是 **`APIWebSocketRoute`**（FastAPI 自己包的），不是 Starlette 那个——
    按全名相等去认会把这条数漏（本卷「按符号局部名认通道」的同族）。"""
    return "WebSocketRoute" in type(route).__name__


class TestEveryCodeSpeakingRouteIsGated:
    def test_registry_enumerates_itself_and_finds_no_ungated_door(self):
        """判据自己数口：除设计上公开的那一条，按码回话的 HTTP 口都得有门。"""
        missing, seen = [], []
        for route in MP.router.routes:
            path = route.path
            if path in PUBLIC_BY_DESIGN:
                continue
            if _isWs(route):
                continue  # WS 不走 Depends：它在处理函数里认 code/token，另有一格审它
            seen.append(path)
            if _gateOf(route) is None:
                missing.append(path)
        assert not missing, (
            f"这些口不带凭证就按码回话（枚举预言机）：{missing}——除 {sorted(PUBLIC_BY_DESIGN)} "
            "之外没有理由开放")
        assert {"/pairing/qrcode/{code}", "/pairing/status/{code}"} <= set(seen), (
            f"本批要关的两个口压根没被数到，这条判据是空跑：{seen}")

    def test_websocket_route_authenticates_inside_the_handler(self):
        """WS 被排除在上面那条门账之外，不等于它是匿名口——它必须在函数体内认凭证。"""
        wsRoutes = [r for r in MP.router.routes if _isWs(r)]
        assert len(wsRoutes) == 1, f"WS 路由数不是 1：{[r.path for r in wsRoutes]}"
        source = inspect.getsource(wsRoutes[0].endpoint)
        assert "4001" in source and "Missing authentication" in source, (
            "WS 处理函数不再拒绝匿名连接——那条豁免就成了无门口的许可证")

    def test_confirm_stays_public_but_keeps_its_rate_limiter(self):
        """公开面是设计不是漏洞：它必须仍然公开，且每 IP 限流还在函数体里。"""
        route = next((r for r in MP.router.routes if r.path == "/pairing/confirm"), None)
        assert route is not None, "confirm 这条路由没了——上面那条豁免名单就成了悬空许可"
        assert _gateOf(route) is None, (
            "confirm 被加上了登录门：手机那一侧没有 JWT，配对流程会当场断掉")
        source = inspect.getsource(route.endpoint)
        assert "_check_confirm_rate_limit" in source, (
            "confirm 公开却丢了每 IP 限流——10^6 个码直接变成可枚举目标，比本批关掉的更糟")

    def test_every_public_door_keeps_its_own_rate_limiter(self):
        """豁免名单每加一口，就要每口各自带闸——否则这条名单变成"无门口的许可证"。

        S1b 新增的 `resolve`（按 ref 换地址）与 `refresh`（按设备身份续签）都是匿名口：
        高熵 ref 不等于不限流（中继会被当成放大器打），可续签更是要防爆破。
        """
        ungated = []
        for path in sorted(PUBLIC_BY_DESIGN):
            route = next((r for r in MP.router.routes if r.path == path), None)
            if route is None:
                ungated.append(f"{path}（路由不存在，豁免名单悬空）")
                continue
            if "_check_confirm_rate_limit" not in inspect.getsource(route.endpoint):
                ungated.append(path)
        assert not ungated, f"这些匿名口没有每 IP 限流：{ungated}"

    def test_gate_detector_hits_a_revived_ungated_route(self):
        """反空转：门摘掉时探测器必须说"没有门"，否则上一条是恒真的空守卫。"""
        import fastapi

        probe = fastapi.APIRouter()

        @probe.get("/pairing/qrcode/{code}")
        async def openQrcode(code: str):  # noqa: ANN001 - 复活样本，刻意不加门
            return {"code": code}

        ungated = [r.path for r in probe.routes if _gateOf(r) is None]
        assert ungated == ["/pairing/qrcode/{code}"], (
            f"探测器对一条明摆着没门的路由说它{[(_gateOf(r)) for r in probe.routes]}——判据不判事")
