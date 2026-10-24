"""回连地址的**对外口径**只允许一处定义，且经代理后必须是 `wss`（设计方案 §7、S0 批）。

现状（2026-10-24 实测）：`_build_ws_url` 的 scheme/host 直接向入站请求要，而全仓
没有任何一处处理 `X-Forwarded-*`，两个真启动点都没开 uvicorn 的 `proxy_headers`
（`neurova/api/app.py:1643`、`start_server.py:141`）。经中继/反代后同时坏两件事：
scheme 判成 http ⇒ 发出去的是 `ws://`（手机在网外连不上），
`request.client.host` 变成代理 IP ⇒ `confirm` 的每 IP 限流对全体手机合并成一个桶。

处置：
- 新增 `NEUROVA_ADVERTISED_BASE_URL` 单源（优先级 advertised > 入站请求），
  **路径仍向路由表要**——批 26 那条判据不因本批松动（`test_mobilePairingAdvertisedWsPathResolves.py`）。
- 启动点开 `proxy_headers=True` + `forwarded_allow_ips`：真实来源 IP 由 uvicorn 的
  代理中间件解析，**不在端点里自己解析一遍 XFF**（那是第二份事实源，教义第 6 条）。

跑法：`.venv/Scripts/python.exe -m pytest -q tests/unit/api/test_mobilePairingAdvertisedBaseUrlSingleSource.py -p no:cacheprovider`
"""
import ast
import io
import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_advertised_01234567")

from neurova.api.endpoints import mobile_pairing as MP  # noqa: E402

PREFIX = "/api/v1/mobile"
REPO = Path(__file__).resolve().parents[3]   # tests/unit/api/<本档> → 仓库根差三级


@pytest.fixture()
def app_and_client():
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: "kai"
    with TestClient(app, base_url="http://testserver") as c:
        yield app, c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()


def _confirmWsUrl(client) -> str:
    gen = client.post(f"{PREFIX}/pairing/generate",
                      json={"device_name": "probe", "device_type": "mobile"}).json()
    conf = client.post(f"{PREFIX}/pairing/confirm",
                       json={"code": gen["code"], "device_name": "probe", "device_id": "d1"})
    assert conf.status_code == 200, conf.text
    return conf.json()["ws_url"]


class TestAdvertisedBaseUrlOverridesInboundHost:
    def test_advertised_host_wins_over_inbound_request(self, app_and_client, monkeypatch):
        """配了对外地址 ⇒ 发出去的回连地址用它，而不是入站那个 `testserver`。"""
        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        url = _confirmWsUrl(c)
        assert "home.example.net" in url, f"对外地址没生效，发出去的仍是入站 host：{url}"
        assert "testserver" not in url, f"入站 host 漏进了回连地址：{url}"

    def test_advertised_https_yields_wss(self, app_and_client, monkeypatch):
        """scheme 跟着对外地址走：https 必须出 `wss://`，手机那侧才连得上。"""
        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        assert _confirmWsUrl(c).startswith("wss://"), _confirmWsUrl(c)

    def test_advertised_may_carry_its_own_path_prefix(self, app_and_client, monkeypatch):
        """反代挂在子路径（`https://x/neurova`）时，前缀必须保住。"""
        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net/neurova")
        url = _confirmWsUrl(c)
        assert url.startswith("wss://home.example.net/neurova/"), url

    def test_without_advertised_the_inbound_request_is_still_used(self, app_and_client, monkeypatch):
        """反向格：没配对外地址时不得变成空地址或写死某个域名——开发环境要照常能扫。"""
        _app, c = app_and_client
        monkeypatch.delenv("NEUROVA_ADVERTISED_BASE_URL", raising=False)
        url = _confirmWsUrl(c)
        assert url.startswith("ws://testserver/"), url

    def test_path_still_comes_from_the_route_table(self, app_and_client, monkeypatch):
        """对外地址只换 host/scheme，路径照旧向路由表要（批 26 判据不松动）。"""
        app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        wsPath = app.router.url_path_for("mobile_websocket")
        url = _confirmWsUrl(c)
        tail = url.split("home.example.net", 1)[1]
        assert tail.startswith(wsPath), f"对外前缀后面接的不是路由表那条路径：{tail} ≠ {wsPath}"


def _callKwargText(sourceText: str, functionName: str) -> str:
    """取 **`uvicorn.run(...)` / `uvicorn.Config(...)`** 调用原文（含 `**` 展开）。

    只按方法名找会先撞上 `asyncio.run(...)` 那类同名调用——把别的调用说了不算带了参数，
    等于判据读错了对象（本卷形态 403）。所以按「接收者是 `uvicorn`」筛。
    """
    tree = ast.parse(sourceText)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute) or callee.attr != functionName:
            continue
        receiver = callee.value
        if not (isinstance(receiver, ast.Name) and receiver.id == "uvicorn"):
            continue
        return ast.unparse(node)
    return ""


class TestStartupEnablesProxyHeaders:
    """两个真启动点都必须带上代理参数，且口径来自 `config.proxyUvicornArgs()` 一处。

    真实来源 IP 的解析**交给 uvicorn 的代理中间件**，不在端点里再 parse 一次
    `X-Forwarded-For`——两处解析同一个头就是两个事实源（教义第 6 条）。
    """

    def test_the_helper_defines_both_settings(self):
        text = (REPO / "neurova/core/config.py").read_text(encoding="utf-8")
        body = re.search(r"def proxyUvicornArgs\(.*?\n(?=\S)", text, re.S)
        assert body, "找不到 `proxyUvicornArgs()`——代理口径得有唯一出处"
        snippet = body.group(0)
        assert "proxy_headers" in snippet, "助手没开 proxy_headers"
        assert "forwarded_allow_ips" in snippet, (
            "开了 proxy_headers 却没限定受信来源：任何人塞一个 X-Forwarded-For 就能伪造"
            "自己的来源 IP，把每 IP 限流绕成没有")

    @pytest.mark.parametrize("relPath", ["neurova/api/app.py", "start_server.py"])
    def test_this_startup_point_carries_the_proxy_args(self, relPath):
        text = (REPO / relPath).read_text(encoding="utf-8")
        call = _callKwargText(text, "run") or _callKwargText(text, "Config")
        assert call, f"{relPath} 里找不到 uvicorn 启动调用——启动点换了，本判据失明"
        assert "proxyUvicornArgs" in call, (
            f"{relPath} 没有带上单源代理参数：经反代后回连地址会出 `ws://` 而不是 `wss://`，"
            "且每 IP 限流会对全体手机合并成一个桶")


def test_the_probe_names_a_startup_call_without_proxy_args():
    """反空转：真造一个不带代理参数的调用，探测器必须报缺，否则上面两条恒真。"""
    sample = "uvicorn.run(app, host='0.0.0.0', port=9527)"
    assert "proxyUvicornArgs" not in _callKwargText(sample, "run"), (
        "探测器对明摆着没带的调用说了带了——判据不判事")


def test_advertised_reader_goes_through_the_config_entrypoint():
    """读法纪律：对外地址经 `neurova/core/config.py` 的统一入口，不散成第二份 `os.getenv`。

    AGENTS/知识档案都点过这个形态——环境变量读取的集中入口就是那四个函数。
    """
    text = (REPO / "neurova/api/endpoints/mobile_pairing.py").read_text(encoding="utf-8")
    body = re.search(r"def _advertisedBaseUrl\(.*?\n(?=\S)", text, re.S)
    assert body, "找不到 `_advertisedBaseUrl()`——对外地址的读处必须唯一"
    snippet = body.group(0)
    assert "config.get" in snippet, f"没走统一配置入口：{snippet}"
