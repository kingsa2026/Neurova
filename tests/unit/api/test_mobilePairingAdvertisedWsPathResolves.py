"""配对链发出去的那条回连地址必须真连得上（§6-172 批 26）。

来历：`_build_ws_url` 把地址**手抄**成 `{ws_scheme}://{host}/mobile/ws`（BE-MOB-001 那次
只修了 host/scheme 的来源，路径仍是抄的）。而本模块的挂载前缀由注册表给：
`("neurova.api.endpoints.mobile_pairing", "/v1/mobile", …)` + `"/api"`
（`endpoints/__init__.py:345`）⇒ 真实路径是 `/api/v1/mobile/ws`，`/mobile/ws` 一条都不存在。

于是这条链上两个出口都在发一个到不了的地址：
- `POST /pairing/confirm` 回的 `ws_url`（手机拿它回连）；
- 批 25 之后那张**能扫了**的二维码，内容也是它（扫完就 1006）。

批 17 的活体脚本证的是「`/api/v1/mobile/ws` 可达」，没有证「发出去的地址就是它」——
两者中间隔着那次手抄，所以链子看着通了、终端还是连不上。

判据走行为读数，不走字符串比对（本仓教训：路由表形状读数读不到挂载后的真实路径）：
1. 真 app 真路由：`generate` → `confirm` 拿到的 `ws_url`，**照它连一次**必须被接受；
2. 校准格（反空转）：一条刻意编错的路径必须连不上——否则第 1 格是"怎么连都不抛"的恒真；
3. 单源：发出去的路径 == 路由表里那条 WebSocket 路由的路径（不在此硬编码 `/api/v1/mobile/ws`）；
4. 形状面：`_build_ws_url` 的函数体里不再有 `/mobile/ws` 那条手抄，改向框架要路径。
"""
import ast
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_ws_path_01234567")

from neurova.api.endpoints import mobile_pairing as MP
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
PREFIX = "/api/v1/mobile"


@pytest.fixture()
def app_and_client():
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()   # 在册设备是持久权威；库由 conftest 指向本用例的 tmp
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: "kai"
    with TestClient(app, base_url="http://testserver") as c:
        yield app, c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()


def _confirmedDevice(c) -> tuple:
    """走真 HTTP 面把配对做完，回 `(发给设备的回连地址, 一次性接入凭证)`。

    S1b 起凭证不在 URL 里（§4.2：这条地址会进中继的访问日志），它随 header 走。
    本档审的是**地址可达**，那一半判据不变；凭证通道由 `test_mobilePairingStateClosure.py` 钉。
    """
    gen = c.post(f"{PREFIX}/pairing/generate",
                 json={"device_name": "probe", "device_type": "mobile"}).json()
    code = gen["code"]
    conf = c.post(f"{PREFIX}/pairing/confirm",
                  json={"code": code, "device_name": "probe", "device_id": "dev-1"})
    assert conf.status_code == 200, conf.text
    body = conf.json()
    return body["ws_url"], body["connect_ticket"]


def _connectOutcome(c, url, ticket: str = ""):
    """行为读数：接受=None，路由不认识=WebSocketDisconnect(code=1000，无 reason)。"""
    parts = urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    headers = {"Authorization": f"Bearer {ticket}"} if ticket else {}
    try:
        with c.websocket_connect(target, headers=headers):
            return None
    except Exception as e:  # noqa: BLE001 - 这里要的就是异常形态
        return getattr(e, "code", "no-code")


class TestAdvertisedAddressIsReachable:
    def test_the_ws_url_we_hand_out_connects(self, app_and_client):
        _app, c = app_and_client
        url, ticket = _confirmedDevice(c)
        outcome = _connectOutcome(c, url, ticket)
        assert outcome is None, (
            f"发出去的回连地址连不上（关闭码 {outcome}）：{url}——手机照着它只能失败一次")

    def test_calibration_a_wrong_path_is_not_connectable(self, app_and_client):
        """这一格保证上一条不是"怎么连都不抛"：把前缀摘掉必须被拒。"""
        _app, c = app_and_client
        url, ticket = _confirmedDevice(c)
        wrong = url.replace(PREFIX, "", 1)
        # 带着**有效凭证**去连错路径：被拒必须是因为路径不存在，不是因为没带凭证
        assert _connectOutcome(c, wrong, ticket) is not None, (
            f"错路径 `{urlsplit(wrong).path}` 也连上了——第 1 格是恒真的空守卫")


class TestAddressComesFromTheRouteTable:
    def test_advertised_path_equals_the_registered_ws_route(self, app_and_client):
        app, c = app_and_client
        # 按形状数 `app.routes` 读不到挂载后的路径（FastAPI 把 include 进来的路由包成
        # `_IncludedRouter`，既无 `.path` 也无数组语义）——问路由表本身要那条名字。
        try:
            wsPath = app.router.url_path_for("mobile_websocket")
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"挂载后的路由表里没有名为 mobile_websocket 的 WS：{e}") from e
        advertised = urlsplit(_confirmedDevice(c)[0]).path
        assert advertised == wsPath, (
            f"发出去的路径 {advertised} ≠ 路由表里的 {wsPath}——前缀是抄的，不是问的")

    def test_builder_no_longer_hardcodes_the_path(self):
        src = (REPO / "neurova/api/endpoints/mobile_pairing.py").read_text(encoding="utf-8")
        body = _functionSource(src, "_build_ws_url")
        assert "/mobile/ws" not in body, "路径又被手抄回来了（挂载前缀的第二份事实源）"
        assert "url_for" in body, "没向框架要路径，就还得靠人记住挂在哪儿"

    def test_detector_hits_a_revived_hardcoded_path(self):
        """反空转：探测器认不出旧那行形态，第 4 格就是恒红或恒真，两种都不判事。"""
        revived = '    return f"{ws_scheme}://{host}/mobile/ws{query}"'
        assert "/mobile/ws" in revived


def _functionSource(source: str, name: str) -> str:
    """函数体源码，**不含 docstring**。

    缘由是老坑重演：`_build_ws_url` 的 docstring 里正写着"原先把 `/mobile/ws` 抄在函数里"，
    连着 docstring 一起查会把自己那句解释算成违例——恒红，且不判事。
    """
    for node in ast.walk(parseSource(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            if not body:
                return ""
            lines = source.splitlines()
            return "\n".join(lines[body[0].lineno - 1: body[-1].end_lineno])
    raise AssertionError(f"没找到函数 {name}——它被改名或删掉了，本判据读不到东西")
