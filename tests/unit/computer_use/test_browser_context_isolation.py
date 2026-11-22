# -*- coding: utf-8 -*-
"""浏览器会话隔离（U20）：playwright context 按属主池化 + 产物属主登记。

U18 核对发现的真实缺口：
1. playwright 是进程级单例单 BrowserContext——所有用户/会话共享同一批
   tab/cookie/localStorage，A 会话写 cookie B 会话可见；
2. browser_pdf/browser_download 产物 stem 无属主段（固定 "browser-pdf" /
   "browser-download"），同名互相覆盖，且不登记生成账本属主 → serve 端反查
   owner 为空 → 任何登录用户可读他人产物。

红绿判据（本文件）：
- 红1：A 的 browser_download 产物 B 读取应 403（改前账本无属主 → 200）；
- 红2：A 会话写 cookie B 会话不可见（改前共享 context → 可见）；
- 绿：两项均隔离。

真实链路（双真 context、真产物、真 serve 路由）由 live-verify 脚本补证；
本文件在层内用 Fake Browser 双属主构造同样的判据，不依赖真浏览器内核。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

import neurova.computer_use.browser_manager as bmmod
from neurova.computer_use.browser_manager import BrowserManager, PlaywrightBackend
from neurova.core.identity_context import clear_request_user_id, set_request_user_id


# ── 测试替身：只替 playwright 的 IO 边界，判据全部打在真实状态上 ────────────


class FakePage:
    def __init__(self, url: str = "https://example.com/page"):
        self.url = url
        self.pdf_calls = 0

    async def goto(self, url: str, wait_until: Optional[str] = None):
        self.url = url
        return None

    async def title(self) -> str:
        return "t"

    async def pdf(self, format: Optional[str] = None) -> bytes:
        self.pdf_calls += 1
        return b"%PDF-fake"

    def on(self, event: str, handler) -> None:
        pass


class FakeRequest:
    def __init__(self, status: int = 200, body: bytes = b"file-bytes"):
        self.status = status
        self._body = body
        self.urls: List[str] = []

    async def get(self, url: str):
        self.urls.append(url)
        return self

    async def body(self) -> bytes:
        return self._body


class FakeContext:
    def __init__(self):
        self.pages: List[FakePage] = []
        self.cookie_jar: List[Dict[str, Any]] = []
        self.request = FakeRequest()
        self.closed = False

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    async def add_cookies(self, cookies: List[Dict[str, Any]]) -> None:
        self.cookie_jar.extend(cookies)

    async def cookies(self, url: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.cookie_jar)

    async def clear_cookies(self) -> None:
        self.cookie_jar.clear()

    async def close(self) -> None:
        self.closed = True

    def on(self, event: str, handler) -> None:
        pass


class FakeBrowser:
    """每次 new_context() 造**新的** context——真实 playwright 的关键语义。"""

    def __init__(self):
        self.contexts: List[FakeContext] = []

    async def new_context(self) -> FakeContext:
        ctx = FakeContext()
        self.contexts.append(ctx)
        return ctx


async def _backend(config: Optional[Dict[str, Any]] = None) -> PlaywrightBackend:
    """经生产装配面造后端：注入 fake browser 后走 initialize()，不绕池化。"""
    b = PlaywrightBackend(config or {})
    b._browser = FakeBrowser()
    b._initialized = True
    return b


@pytest.fixture(autouse=True)
def _isolateIdentityAndLedger(monkeypatch, tmp_path):
    """身份/会话上下文与账本落盘逐用例隔离，防跨用例污染。"""
    from neurova.llm.generators import runtime as runtimeMod
    from neurova.llm.generators import task_ledger as ledgerMod
    from neurova.core import turn_context as turnMod

    monkeypatch.setattr(runtimeMod, "GENERATION_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ledgerMod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")
    # generation.py 在 import 时刻快照产物目录（_GENERATION_OUTPUT_DIR）——
    # 本文件无论单独跑还是跟其他套件同进程跑，都必须把它钉到同一 tmp 目录，
    # 否则 serve 判据依赖模块首次导入顺序（隐性顺序耦合）。
    from neurova.api.endpoints import generation as generationMod

    monkeypatch.setattr(generationMod, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    ledgerMod.reset_generation_task_ledger()
    turnMod.set_turn_identity("isolation-test", None)
    yield
    clear_request_user_id()
    turnMod.set_turn_identity("isolation-test", None)
    ledgerMod.reset_generation_task_ledger()


# ── 属主键单源 ───────────────────────────────────────────────────────────────


class TestResolveBrowserOwnerKey:
    def test_userIdentityWins(self):
        set_request_user_id("alice")
        assert bmmod.resolveBrowserOwnerKey() == "user:alice"

    def test_fallsBackToTurnSessionWhenNoUser(self):
        from neurova.core.turn_context import set_turn_identity

        set_turn_identity("hello", "sess-42")
        assert bmmod.resolveBrowserOwnerKey() == "agent:sess-42"

    def test_defaultWhenNoIdentityAtAll(self):
        assert bmmod.resolveBrowserOwnerKey() == "default"


# ── 红2：context 池化与 cookie 隔离 ─────────────────────────────────────────


class TestContextPooling:
    @pytest.mark.asyncio
    async def test_contextsAreIndependentPerOwner(self):
        b = await _backend()
        set_request_user_id("alice")
        ctxA1 = await b._contextForOwner()
        ctxA2 = await b._contextForOwner()
        assert ctxA1 is ctxA2, "同属主复用同一 context（池化）"
        set_request_user_id("bob")
        ctxB = await b._contextForOwner()
        assert ctxB is not ctxA1, "不同属主必须拿到不同 context（cookie/storage 隔离）"

    @pytest.mark.asyncio
    async def test_poolEvictsLeastRecentlyUsedBeyondCap(self):
        b = await _backend({"max_user_contexts": 2})
        set_request_user_id("alice")
        ctxA = await b._contextForOwner()
        set_request_user_id("bob")
        await b._contextForOwner()
        set_request_user_id("carol")
        ctxC = await b._contextForOwner()
        assert ctxA.closed, "超上限时最久未用的 alice context 必须被关闭"
        assert list(b._userContexts.keys()) == ["user:bob", "user:carol"]
        assert b._userContexts["user:carol"] is ctxC

    @pytest.mark.asyncio
    async def test_ensureOwnerSessionBootstrapsFreshOwnerPage(self):
        b = await _backend()
        set_request_user_id("alice")
        await b.ensureOwnerSession()
        pageA = b._page
        assert pageA is not None
        set_request_user_id("bob")
        await b.ensureOwnerSession()
        assert b._page is not None and b._page is not pageA, "新属主拿到自己的页，不踩 A 的 tab"
        assert b._userContexts["user:alice"] is not b._userContexts["user:bob"]

    @pytest.mark.asyncio
    async def test_cookieWriteDoesNotLeakAcrossOwners(self):
        """红2：A 会话写 cookie，B 会话读不到。"""
        b = await _backend()
        set_request_user_id("alice")
        await b.ensureOwnerSession()
        set_result = await b.cookies(action="set", name="session-token", value="alice-secret", url="https://example.com")
        assert set_result.success
        set_request_user_id("bob")
        await b.ensureOwnerSession()
        got = await b.cookies(action="get")
        assert got.success
        leaked = [c for c in got.data if c.get("name") == "session-token"]
        assert leaked == [], "B 会话不得读到 A 会话写的 cookie"

    @pytest.mark.asyncio
    async def test_tabsAreOwnerScoped(self):
        b = await _backend()
        set_request_user_id("alice")
        await b.ensureOwnerSession()
        openedA = await b.open_target("https://example.com/a")
        targetA = openedA.data["target_id"]
        set_request_user_id("bob")
        await b.ensureOwnerSession()
        listing = await b.list_targets()
        assert all(t["target_id"] != targetA for t in listing.data), "B 的 tab 列表不得出现 A 的 tab"
        switched = await b.switch_target(targetA)
        assert not switched.success, "B 不得切换到 A 的 tab"


# ── 红1：产物 stem 属主段 + 账本属主登记 + serve 归属校验 ────────────────────


class TestArtifactOwnership:
    @pytest.mark.asyncio
    async def test_downloadStemCarriesOwnerAndUniqueSuffix(self, tmp_path):
        b = await _backend()
        set_request_user_id("alice")
        await b.ensureOwnerSession()
        r1 = await b.download_file("https://example.com/f/data.csv")
        r2 = await b.download_file("https://example.com/f/data.csv")
        assert r1.success and r2.success
        name1, name2 = r1.data["file_name"], r2.data["file_name"]
        assert name1 != name2, "同属主两次下载也不得同名覆盖"
        assert name1.endswith(".csv") and name2.endswith(".csv"), "扩展名保持不变"
        assert "alice" in name1, "stem 必须带属主段"

    @pytest.mark.asyncio
    async def test_pdfStemCarriesOwnerAndLedgerRegistration(self):
        b = await _backend()
        set_request_user_id("alice")
        await b.ensureOwnerSession()
        r1 = await b.print_pdf()
        r2 = await b.print_pdf()
        assert r1.success and r2.success
        assert r1.data["file_name"] != r2.data["file_name"], "两次 PDF 不得同名覆盖"
        assert "alice" in r1.data["file_name"]
        from neurova.llm.generators.task_ledger import get_generation_task_ledger

        owners = {t.owner_user_id for t in get_generation_task_ledger().list()}
        assert "alice" in owners, "browser_pdf 产物必须登记生成账本属主（原始 user id，与 serve 端比对同命名空间）"

    @pytest.mark.asyncio
    async def test_persistBytesOwnerParamRegistersLedger(self, tmp_path):
        from neurova.llm.generators.runtime import persist_bytes
        from neurova.llm.generators.task_ledger import get_generation_task_ledger

        path = await persist_bytes(b"x", "pdf", "stem-owned", owner_user_id="alice", session_id="s1", kind="browser_pdf")
        records = [t for t in get_generation_task_ledger().list() if t.local_path == path]
        assert len(records) == 1 and records[0].owner_user_id == "alice"
        assert records[0].session_id == "s1"
        # 未传属主 → 行为不变（不登记）
        path2 = await persist_bytes(b"y", "pdf", "stem-legacy")
        records2 = [t for t in get_generation_task_ledger().list() if t.local_path == path2]
        assert records2 == [], "默认不传属主必须保持既有行为（零登记）"

    @pytest.mark.asyncio
    async def test_serveBlocksOtherUsersFromOwnedArtifact(self):
        """红1：A 的产物 B 读取必须 403（改前账本无属主 → 任何登录用户 200）。"""
        from fastapi import HTTPException

        from neurova.api.endpoints.generation import serve_generation_file
        from neurova.llm.generators.runtime import persist_bytes

        path = await persist_bytes(b"secret", "pdf", "owned-artifact", owner_user_id="alice")
        name = path.split("\\")[-1].split("/")[-1]
        with pytest.raises(HTTPException) as ei:
            await serve_generation_file(None, name, {"user_id": "bob", "role": "user"})
        assert ei.value.status_code == 403, "B 读 A 的产物必须被拒"
        resp = await serve_generation_file(None, name, {"user_id": "alice", "role": "user"})
        assert resp.status_code == 200
        respAdmin = await serve_generation_file(None, name, {"user_id": "admin1", "role": "admin"})
        assert respAdmin.status_code == 200


# ── 车道键属主段 ─────────────────────────────────────────────────────────────


class TestLaneKeyOwnerSegment:
    def test_laneKeyDiffersAcrossOwners(self):
        from neurova.computer_use.lane_mutex import activeSessionKey

        manager = BrowserManager(config={})
        manager._active_backend = PlaywrightBackend({})
        set_request_user_id("alice")
        keyA = activeSessionKey(manager)
        set_request_user_id("bob")
        keyB = activeSessionKey(manager)
        assert keyA != keyB, "不同属主的浏览器车道键必须不同"
        assert keyA.startswith("user:alice:"), f"车道键须以属主段开头: {keyA}"
