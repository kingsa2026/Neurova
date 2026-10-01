"""camofox 后端产出侧语义 —— 真 HTTP 传输上的入库守卫（T-12 收尾 · 工单集 U-07）

补的断链：入库的既有 camofox 判据经 `_make_backend`
（`tests/unit/computer_use/test_camofox_server_backend.py:37`）把 `b._client` 整个换成
MagicMock —— httpx 对象本身都不是真的，所以"空正文不被当成功快照"这件事
**从未 over 一条真 socket 验证过**。本文件把对端换成仓内起的最小 HTTP 服务：
真 httpx AsyncClient、真 TCP 连接、真 JSON 编解码、真 tab 注册，只有服务本身是桩。

**边界（误读就会把这判据当成活体）**：桩的响应形状按 `camofox_server_backend` 自家读点
（`tabId` / `snapshot` / `refsCount` / `truncated` / `url`）声明，因此本文件证明的是
"**我们对契约的解释在真传输上自洽**"，不是"**真实服务就返回这个形状**"。后者要授权起
外部服务才能验，见 `docs/specs/2026-10-01-computer-use-perception-closure.md` 的 U-08。

每例点名的生产改动（判据会咬的那一条）：
- 握手：health 失败仍置就绪 ⇒ 第一例红；health 失败后绕过 supervisor 直接起进程 ⇒ 第二例红。
- tab 绑定：`tabId` 读错成别的键 ⇒ 后续快照打到 `/tabs//snapshot`，第三例红。
- 空正文：`dom_snapshot` 的空正文分支被摘 ⇒ 第四例红（T-12 原始谎报形态）。
- 缺口后动作：不看 `snap.success` 就继续按 ref 动作 ⇒ 第五例红（动作请求出现在记录里）。
"""
import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

import pytest

from neurova.computer_use.browser_manager import EMPTY_SNAPSHOT_MARKER

STUB_TAB_ID = "cf-tab-1"
STUB_URL = "https://example.test/orders"
# 手推字面量，不由被测代码算出：容器返回的快照正文与 refs 条数
SNAPSHOT_TEXT = "- document:\n  - button: 提交订单 [e1]\n  - textbox: 数量 [e2]\n"


class _StubHandler(BaseHTTPRequestHandler):
    """按本仓既有 camofox 读点声明的最小对端；只应答与记录，不做任何判断。"""

    state: Dict[str, Any] = {}

    def log_message(self, fmt, *args):  # 静音，别污染测试输出
        return

    def _record(self, method: str) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.state.setdefault("requests", []).append(f"{method} {self.path}")
        return body

    def _reply(self, payload: Dict[str, Any], code: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 —— BaseHTTPRequestHandler 约定的方法名
        self._record("GET")
        route = self.path.split("?", 1)[0]
        if route.startswith("/health"):
            return self._reply({"ok": True})
        if route.endswith("/snapshot"):
            return self._reply({
                "snapshot": self.state.get("snapshot", SNAPSHOT_TEXT),
                "refsCount": 2,
                "truncated": False,
                "url": STUB_URL,
            })
        return self._reply({"error": "not-found"}, code=404)

    def do_POST(self):  # noqa: N802
        body = self._record("POST")
        route = self.path.split("?", 1)[0]
        sent = {}
        if body:
            try:
                sent = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                sent = {}
        if route == "/tabs":
            return self._reply({"tabId": STUB_TAB_ID, "url": sent.get("url", STUB_URL)})
        if route.endswith("/navigate"):
            return self._reply({"url": sent.get("url", STUB_URL)})
        if route.endswith("/click") or route.endswith("/type"):
            return self._reply({"ok": True})
        return self._reply({"error": "not-found"}, code=404)


class _ThreadedStubServer(socketserver.ThreadingMixIn, HTTPServer):
    """每请求一线程：asyncio 侧的 httpx 与 server 侧互不阻塞。"""

    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture
def stub():
    """起桩、给出 base_url 与请求日志，用例结束后收摊。"""
    _StubHandler.state = {"snapshot": SNAPSHOT_TEXT, "requests": []}
    server = _ThreadedStubServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield {
            "base_url": f"http://{host}:{port}",
            "requests": _StubHandler.state["requests"],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def stubSnapshot():
    """换桩的快照正文（只动对端应答，不碰被测代码）。"""
    def _set(text: str) -> None:
        _StubHandler.state["snapshot"] = text
    return _set


class _SupervisorSpy:
    """替身 supervisor —— 真实现会拉起外部服务，测试绝不能触到它。"""

    def __init__(self, start_ok: bool):
        self.calls: List[str] = []
        self._start_ok = start_ok

    async def ensure_started(self) -> bool:
        self.calls.append("ensure_started")
        return self._start_ok

    def record_activity(self) -> None:
        self.calls.append("record_activity")


def _stubSupervisor(monkeypatch, start_ok: bool) -> _SupervisorSpy:
    import neurova.computer_use.camofox_supervisor as supervisor_module

    spy = _SupervisorSpy(start_ok)
    monkeypatch.setattr(supervisor_module, "get_camofox_supervisor", lambda: spy)
    return spy


class TestCamofoxRealSocketContract:
    """正对照：真传输上拿到的字段必须原样进 BrowserResult。"""

    @pytest.mark.asyncio
    async def test_healthyHandshakeArmsBackendWithoutTouchingSupervisor(self, stub, monkeypatch):
        """对端活着 ⇒ 就绪，且**不去拉外部服务**。"""
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        spy = _stubSupervisor(monkeypatch, start_ok=False)
        backend = CamofoxServerBackend({"base_url": stub["base_url"]})
        try:
            assert await backend.initialize() is True
            assert "ensure_started" not in spy.calls
            assert any(path == "GET /health" for path in stub["requests"])
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_unreachableHealthStaysUnreadyAndAsksSupervisorOnce(self, monkeypatch):
        """对端没起 ⇒ 不许谎报就绪；拉起与否的决定权交回 supervisor（此处替身）。"""
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        spy = _stubSupervisor(monkeypatch, start_ok=False)
        reserve = socketserver.TCPServer(("127.0.0.1", 0), _StubHandler)
        host, port = reserve.server_address
        reserve.server_close()  # 端口无人监听
        backend = CamofoxServerBackend({"base_url": f"http://{host}:{port}"})
        try:
            assert await backend.initialize() is False
            assert spy.calls == ["ensure_started"]
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_navigateBindsContainerTabIdToFollowingRequests(self, stub):
        """`POST /tabs` 回 `tabId` ⇒ 后续请求打到**那个** tab，而不是空路径。"""
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        backend = CamofoxServerBackend({"base_url": stub["base_url"]})
        try:
            assert await backend.initialize() is True
            res = await backend.navigate(STUB_URL)
            assert res.success is True
            assert res.url == STUB_URL
            assert res.generation == 1
            snap = await backend.dom_snapshot()
            assert snap.success is True
            snapshotPaths = [p for p in stub["requests"] if "/snapshot" in p]
            # 只钉 tab 绑定，不钉 query（userId 由身份上下文决定，不是本例的契约）
            assert len(snapshotPaths) == 1, snapshotPaths
            assert snapshotPaths[0].startswith(f"GET /tabs/{STUB_TAB_ID}/snapshot"), snapshotPaths
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_nonEmptySnapshotKeepsContainerTextAndCounts(self, stub):
        """非空正文是**成功**：正文逐字来自容器，refsCount/truncated 一并上报。

        这条是反向对照：把"空正文要拒"修成"所有快照都拒"，它当场红。
        """
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        backend = CamofoxServerBackend({"base_url": stub["base_url"]})
        try:
            assert await backend.initialize() is True
            await backend.navigate(STUB_URL)
            res = await backend.dom_snapshot()
            assert res.success is True
            assert res.data["snapshot"] == SNAPSHOT_TEXT
            assert res.data["refs_count"] == 2
            assert res.data["truncated"] is False
        finally:
            await backend.close()


class TestBlankSnapshotRefusalOverSocket:
    """T-12 的原始形态：空正文曾以 `success=True` + 空正文谎报成功。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blank", ["", "   \n  "])
    async def test_blankSnapshotFailsWithNamedMarkerNotEmptySuccess(
        self, stub, stubSnapshot, blank
    ):
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        backend = CamofoxServerBackend({"base_url": stub["base_url"]})
        try:
            assert await backend.initialize() is True
            await backend.navigate(STUB_URL)
            stubSnapshot(blank)
            res = await backend.dom_snapshot()
            assert res.success is False, "空正文又被判成成功 —— T-12 的谎报形态复现"
            assert EMPTY_SNAPSHOT_MARKER in (res.error or ""), "拒了却不带具名 marker"
            assert (res.data or {}).get("snapshot") in (None, ""), "失败结果里不该还挂着正文"
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_actionAfterBlankSnapshotSendsNoClickToContainer(self, stub, stubSnapshot):
        """缺口之后动作必须被拒，且**一个动作请求都不许发到容器**。"""
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        backend = CamofoxServerBackend({"base_url": stub["base_url"]})
        try:
            assert await backend.initialize() is True
            await backend.navigate(STUB_URL)
            stubSnapshot("")
            assert (await backend.dom_snapshot()).success is False
            refused = await backend.click_role("button", "提交订单")
            assert refused.success is False
            assert not [p for p in stub["requests"] if p.endswith("/click")], \
                "拒绝路径上把动作真发出去了 —— 没拿到事实却按旧 ref 点击"
        finally:
            await backend.close()
