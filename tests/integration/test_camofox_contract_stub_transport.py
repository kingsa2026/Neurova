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
- 握手：health 失败仍置就绪 ⇒ 红；**宿主没显式开过 autostart 却去问 supervisor** ⇒
  `test_defaultAutostartNeverAsksSupervisorOnHealthFailure` 红（默认路径 = agent 首次调用
  拉起外部服务，这条不该在 agent 手里）；反过来把这条路整个删掉（显式开过也不问）⇒
  `test_explicitAutostartStillAsksSupervisorOnce` 红。
- 装配点：选路命中 camofox 时不查能力读数 ⇒ `test_unreachableCamofox...` 红；
  把守卫修成"永远拒绝" ⇒ `test_reachableCamofoxPassesAssemblyGuard` 红。
- tab 绑定：`tabId` 读错成别的键 ⇒ 后续快照打到 `/tabs//snapshot`，该例红。
- 空正文：`dom_snapshot` 的空正文分支被摘 ⇒ 两参皆红（T-12 原始谎报形态）。
- 缺口后动作：不看 `snap.success` 就继续按 ref 动作 ⇒ 红（动作请求出现在记录里）。
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

    def __init__(self, start_ok: bool, explicitAutostart: bool = False):
        self.calls: List[str] = []
        self._start_ok = start_ok
        self._explicit = explicitAutostart

    async def ensure_started(self) -> bool:
        self.calls.append("ensure_started")
        return self._start_ok

    def record_activity(self) -> None:
        self.calls.append("record_activity")

    def autostartExplicit(self) -> bool:
        """宿主是否**显式**开过 autostart（默认值不算，Q-4 乙案的判据口径）。"""
        return self._explicit


def _stubSupervisor(monkeypatch, start_ok: bool, explicitAutostart: bool = False) -> _SupervisorSpy:
    import neurova.computer_use.camofox_supervisor as supervisor_module

    spy = _SupervisorSpy(start_ok, explicitAutostart)
    monkeypatch.setattr(supervisor_module, "get_camofox_supervisor", lambda: spy)
    return spy


def _deadPortUrl() -> str:
    """确定连不通的地址（`127.0.0.1:1` 在本机回 ECONNREFUSED，属权限端口无人监听）。

    别用"占一个临时端口再释放"的写法：本机实测那个端口会被系统代理接走并回 **502**，
    分支虽然同走"不可达"，但读数不再是"无人监听"，换机器就可能变。
    """
    return "http://127.0.0.1:1"


@pytest.fixture
def camofoxOnlyManager(monkeypatch):
    """造一个"只有 camofox 这条后端"的 BrowserManager 单例并负责收摊。

    为什么必须走单例而不是直接 new：`capability_state._probeCamofox` 探的是
    `get_browser_manager()` 那一份（它不按 manager 分键），直接 new 会读出别人的配置。
    """
    from neurova.computer_use import browser_manager as bm
    from neurova.computer_use import capability_state

    monkeypatch.setattr(bm, "HAS_PLAYWRIGHT", False)
    monkeypatch.setattr(bm, "HAS_SCRAPLING", False)
    monkeypatch.delenv("NEUROVA_CAMOFOX_URL", raising=False)
    monkeypatch.delenv("NEUROVA_CAMOFOX_AUTOSTART", raising=False)

    def _make(baseUrl: str):
        bm.reset_browser_manager()
        capability_state.invalidate("camofox")
        return bm.get_browser_manager(config={"camofox": {"enabled": True, "base_url": baseUrl}})

    yield _make
    bm.reset_browser_manager()
    capability_state.invalidate("camofox")


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
    async def test_defaultAutostartNeverAsksSupervisorOnHealthFailure(self, monkeypatch):
        """对端没起、宿主也没显式开过 autostart ⇒ **连问都不问**，不谎报就绪也不起服务。

        这条是 Q-4 拍板后**改了期望值**的那条。原名
        `test_unreachableHealthStaysUnreadyAndAsksSupervisorOnce` 把"health 失败就把决定权
        交给 supervisor"钉成活契约；而 `NEUROVA_CAMOFOX_AUTOSTART` 默认为 True，
        那条默认路径就等于让 agent 的首次浏览器调用去拉起外部服务。应然改成：
        **默认不拉起，宿主显式开过才问**（owner 归 host）。
        """
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        monkeypatch.delenv("NEUROVA_CAMOFOX_AUTOSTART", raising=False)
        spy = _stubSupervisor(monkeypatch, start_ok=False)
        backend = CamofoxServerBackend({"base_url": _deadPortUrl()})
        try:
            assert await backend.initialize() is False
            assert "ensure_started" not in spy.calls, \
                "默认路径去问了 supervisor —— 拉起外部服务的决定权不该在 agent 手里"
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_explicitAutostartStillAsksSupervisorOnce(self, monkeypatch):
        """宿主显式把 autostart 设为真 ⇒ 照旧交 supervisor 决定（别把这条路改成生产死码）。"""
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        monkeypatch.setenv("NEUROVA_CAMOFOX_AUTOSTART", "true")
        spy = _stubSupervisor(monkeypatch, start_ok=False, explicitAutostart=True)
        backend = CamofoxServerBackend({"base_url": _deadPortUrl()})
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


class TestAssemblyRefusesUnreachableCamofox:
    """Q-4 乙案的装配点：选路命中 camofox 就先问能力读数，不可达且未显式开 autostart ⇒ 具名拒绝。

    咬住的改动：这道守卫被摘掉（退回"配置位说启用就选它"），或拒绝路径仍去问 supervisor。
    """

    @pytest.mark.asyncio
    async def test_unreachableCamofoxRefusedAtAssemblyWithoutAskingSupervisor(
        self, camofoxOnlyManager, monkeypatch
    ):
        spy = _stubSupervisor(monkeypatch, start_ok=False)
        manager = camofoxOnlyManager(_deadPortUrl())
        with pytest.raises(RuntimeError) as caught:
            await manager.navigate(STUB_URL)
        text = str(caught.value)
        assert "capability-camofox-configured-unreachable" in text, text
        assert "autostart" in text.lower(), "拒绝文案要点名宿主能扳的那个开关"
        assert "ensure_started" not in spy.calls, \
            "装配点仍去问 supervisor —— 默认路径就是一次外部进程拉起"

    @pytest.mark.asyncio
    async def test_reachableCamofoxPassesAssemblyGuard(
        self, camofoxOnlyManager, stub, monkeypatch
    ):
        """反向对照：服务真在跑 ⇒ 守卫放行并按 camofox 走通（不许修成"永远拒绝"）。"""
        spy = _stubSupervisor(monkeypatch, start_ok=False)
        manager = camofoxOnlyManager(stub["base_url"])
        res = await manager.navigate(STUB_URL)
        assert res.success is True, res.error
        assert "ensure_started" not in spy.calls, \
            "可达的服务不需要被拉起（`record_activity` 只刷 idle 计时，不算拉起）"
        assert "POST /tabs" in stub["requests"]
