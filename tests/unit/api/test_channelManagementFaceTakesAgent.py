# -*- coding: utf-8 -*-
"""渠道管理面也有"只看 default"的半边——连同它的契约文本一起收口（§6-190 批 29）。

§6-189 补的是**入站回调**的解析；本格管的是同一个 router 里剩下的那半边，四条都现量：

1. **模块 docstring 的路径清单是假的**：它写 `GET /api/v1/channel-adapters/channels/{type}` 等
   七条，而真注册是 `("neurova.api.endpoints.channels", "/v1/channel-adapters")` +
   `@router.get("/{channel_type}")` ⇒ 实际地址里**没有 `/channels` 那一段**；且它漏记了前端真正在用的
   三条（restart / clear-queue / conflicts/check）。`docs/06-bugfix` 里那句"已更新 docstring 反映新
   路由路径"改的正是这次前缀变更——改了注册表，没把 docstring 改对，于是留下一个看起来权威的错清单。
   判据按**真路由表**双向比：docstring 声明的每条都要存在、真路由每条都要被声明（只审"已登记的"
   那一族，本仓记过：漏项恒绿零红）。
2. **管理端点带不了 agent**：`GET /{type}`、`POST /{type}/connect`、`/disconnect`、`/send` 四个都是
   `get_adapter(channel_type)` / `manager.send_message(...)` 不传 agent，而同一个 router 里的
   `restart`、`clear-queue` 早就收了 `agent_id` Query（前端确实带）。于是"重启能精确到 agent、
   断开/查状态/发消息只能碰 default"——同一资源两种口径。
3. **`health_check()` 的定义域也只到 default**：`list_channels` 与 `/health/all` 两个端点都用它，
   而它遍历 `self._adapters`（default 兼容视图）。跨 agent 的全量视图其实**已经有实现**——
   `list_adapters()`，含"default 裸键、其余 `agent:channel`"这套键约定。所以这不是缺功能，
   是同域两份口径：探活那份弱、列表那份强，对外端点偏偏用了弱的。
4. **`replace_channel` 是第二份"换实例"实现且零调用者**：现役那份在 `channel_config.py` 的保存路径里
   （拆旧连接 → 注销 → 工厂下沉线程池 → 注册 → 连接，还管 needs_scan 与落盘），比它做得更多且带 agent；
   `replace_channel` 既没人调、内部又是 default-only（接上就错投）。按教义第 7 的比-取-接-退：
   比较与替代都成立 ⇒ 退役，并从 §6-189 那张欠账表里销行。
"""

import ast
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

REPO = pathlib.Path(__file__).resolve().parents[3]
CHANNELS_PY = REPO / "neurova" / "api" / "endpoints" / "channels.py"
CHANNELS_SRC = CHANNELS_PY.read_text(encoding="utf-8")

from neurova.api.app import create_app  # noqa: E402
from neurova.channels.base import ChannelConfig  # noqa: E402
from neurova.channels.feishu import FeishuAdapter  # noqa: E402
from neurova.channels.manager import ChannelManager, get_channel_manager  # noqa: E402

ADAPTER_PREFIX = "/api/v1/channel-adapters"
#: 该 router 的模块名（取路由面用 router.routes，不是 app.routes——见 `_realRoutesOfTheRouter` 的说明）
ROUTER_MODULE = "neurova.api.endpoints.channels"


def _normalized(template: str) -> str:
    """把 `{channel_type}`/`{type}`、空段与多余斜杠归一，比的是形状不是字面写法。"""
    tail = template
    if tail.startswith(ADAPTER_PREFIX):
        tail = tail[len(ADAPTER_PREFIX):]
    tail = tail.strip()
    if tail in ("", "/"):
        return ""
    return ("/" + tail.strip("/")).replace("{channel_type}", "{X}").replace("{type}", "{X}")


def _docstringRoutes(src: str) -> list:
    """模块头那段路由清单里声明的 (方法, 路径)。

    刻意不用 `ast.get_docstring`：这个文件的清单串排在 `from __future__` 与 import 之后，
    根本不是合法的模块 docstring——`get_docstring` 对它返回 None，第一版就在这里把"取不到"
    读成了"没有声明"，于是一格该红的比对假绿了（取数器为空与断言为空是两回事）。
    """
    entries = []
    for line in src.splitlines():
        m = re.match(r"^-+\s+([A-Z]+)\s+(\S+)\s+-", line.strip())
        if m:
            entries.append((m.group(1), _normalized(m.group(2))))
    return entries


def _realRoutesOfTheRouter() -> dict:
    """该 router 真正注册出去的面：`{归一路径: 方法集合}`。

    取 `router.routes` 而不是 `app.routes`——本仓挂载走 `_IncludedRouter`，`app.routes` 95 条里
    只有 5 条带 `.path`（那一形本卷记过），拿它当真路由表会近乎空集，于是"声明的每条都存在"
    这种断言自动成立。这里再加一道地板断言：空集就是口径失效，不许当成"没有差异"。
    """
    import importlib

    router = importlib.import_module(ROUTER_MODULE).router
    out = {}
    for route in router.routes:
        path = getattr(route, "path", None)
        assert isinstance(path, str), f"路由条目没有 path，取数口径失效：{route!r}"
        out.setdefault(_normalized(path), set()).update(getattr(route, "methods", None) or set())
    assert out, "router.routes 取到空集——空集不等于'契约与实现一致'"
    return out


def _contractDiffs(declared: list, real: dict) -> dict:
    """双向差集：契约多写的、实现里有而契约没写的、方法名对不上的。"""
    byPath: dict = {}
    for method, path in declared:
        byPath.setdefault(path, set()).add(method)
    return {
        "契约里有、路由里没有": sorted(set(byPath) - set(real)),
        "路由里有、契约没写": sorted(set(real) - set(byPath)),
        "方法名不吻合": sorted(p for p in set(byPath) & set(real) if not byPath[p] <= real[p]),
    }


@pytest.fixture()
def twoAgents(tmp_path):
    """两只不同 agent 名下的同名渠道实例；对它们的适配器方法各装一个记录器。

    登录门是装配噪声不是被测行为，这里覆盖 `get_current_user`；但 `create_app()` 有缓存实例，
    覆盖**必须**在退出时清干净，否则会泄漏给下一档用同一只 app 的测试（本仓记过那一形）。
    """
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    from neurova.api.deps import get_current_user

    isolatedDataRoot()
    ChannelManager._instance = None
    calls = {"status": [], "connect": [], "disconnect": [], "send": []}
    adapters = {}

    def _make(agentId):
        adapter = FeishuAdapter(ChannelConfig(
            channel_type="feishu", app_id=f"cli_{agentId}", app_secret="sec",
            verification_token="tok", use_stream=False))
        adapter._agentTag = agentId

        async def _health():
            calls["status"].append(agentId)
            return {"channel_type": "feishu", "agent_id": agentId, "connected": True}

        async def _connect():
            calls["connect"].append(agentId)
            return True

        async def _disconnect():
            calls["disconnect"].append(agentId)
            return None

        adapter.health_check = _health
        adapter.connect = _connect
        adapter.disconnect = _disconnect
        adapters[agentId] = adapter
        return adapter

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: {"sub": "tester-b29"}
        mgr = get_channel_manager()
        for agentId in ("default", "kai"):
            mgr.register_adapter(_make(agentId), agent_id=agentId)
        try:
            yield client, mgr, calls
        finally:
            client.app.dependency_overrides.pop(get_current_user, None)
    ChannelManager._instance = None


class TestContractTextMatchesTheRealRouteTable:
    """契约文本与真路由表双向比：多写一条要红，少写一条也要红。"""

    def testEveryDocumentedRouteExists(self):
        declared = _docstringRoutes(CHANNELS_SRC)
        assert len(declared) >= 10, f"取数器只抓到 {len(declared)} 条声明——口径失效，不是'没写'"
        diffs = _contractDiffs(declared, _realRoutesOfTheRouter())
        assert diffs["契约里有、路由里没有"] == [], (
            f"docstring 声明了真路由表里不存在的地址：{diffs['契约里有、路由里没有']}")
        assert diffs["方法名不吻合"] == [], (
            f"路径在、方法不对（GET 写成 POST 这类）：{diffs['方法名不吻合']}")

    def testEveryRealRouteIsDocumented(self):
        declared = _docstringRoutes(CHANNELS_SRC)
        diffs = _contractDiffs(declared, _realRoutesOfTheRouter())
        assert diffs["路由里有、契约没写"] == [], (
            f"真路由有 {len(diffs['路由里有、契约没写'])} 条没被清单记到："
            f"{diffs['路由里有、契约没写']}")

    def testComparatorHasTeeth(self):
        """自证：比对器对"多一条 / 少一条 / 方法名错 / 多一段"四样都真会红。

        第一版就在这里空转——`ast.get_docstring` 对本文件返回 None、`app.routes` 又近乎空集，
        于是两侧皆空、差集皆空，两格"该红的比对"绿得没道理。这里喂的都是必命中的形状。
        """
        real = _realRoutesOfTheRouter()
        ok = [(m, p) for p, ms in real.items() for m in sorted(ms)]
        assert _contractDiffs(ok, real) == {
            "契约里有、路由里没有": [], "路由里有、契约没写": [], "方法名不吻合": []}, \
            "同一份面自比却报差异——归一化没做对"

        phantom = ok + [("GET", "/api/v1/channel-adapters/channels/ghost")]
        assert _contractDiffs(phantom, real)["契约里有、路由里没有"], "多写一条假地址却没报"

        dropped = ok[:-1]
        assert _contractDiffs(dropped, real)["路由里有、契约没写"], "漏记一条真路由却没报"

        wrongMethod = [("POST" if m == "GET" else "GET", p) for m, p in ok]
        assert _contractDiffs(wrongMethod, real)["方法名不吻合"], "方法名整体写反却没报"

        assert _normalized("/api/v1/channel-adapters/{type}") == \
            _normalized("/api/v1/channel-adapters/{channel_type}"), "参数名不同形被判成两条地址"


class TestManagementEndpointsTakeAgentDimension:
    def testStatusHitsTheAskedAgent(self, twoAgents):
        client, mgr, calls = twoAgents
        r = client.get(f"{ADAPTER_PREFIX}/feishu", params={"agent_id": "kai"})

        assert r.status_code == 200, f"{r.status_code} {r.text[:120]}"
        assert calls["status"] == ["kai"], f"探活打到的是 {calls['status']}"

    def testConnectAndDisconnectHitTheAskedAgent(self, twoAgents):
        client, mgr, calls = twoAgents
        body = {"use_stream": False}
        r1 = client.post(f"{ADAPTER_PREFIX}/feishu/disconnect", params={"agent_id": "kai"})
        r2 = client.post(f"{ADAPTER_PREFIX}/feishu/connect", params={"agent_id": "kai"}, json=body)

        assert r1.status_code == 200 and r2.status_code == 200, f"{r1.status_code}/{r2.status_code}"
        assert calls["disconnect"] == ["kai"], f"断开打到了 {calls['disconnect']}"
        assert calls["connect"] == ["kai"], f"连接打到了 {calls['connect']}"

    def testSendCarriesTheAgentDimensionDown(self, twoAgents):
        """这一格断的是"端点把 agent 维度交下去了"，所以打桩在 `manager.send_message` 那道接缝上——
        再往下就要真连接与真凭据，不是本批主张的东西。"""
        client, mgr, calls = twoAgents
        original = mgr.send_message

        async def _spy(**kwargs):
            calls["send"].append((kwargs.get("agent_id"), kwargs.get("channel_type")))
            return "msg-ok"

        mgr.send_message = _spy
        try:
            r = client.post(f"{ADAPTER_PREFIX}/feishu/send", params={"agent_id": "kai"},
                            json={"chat_id": "oc_1", "content": "hi"})
        finally:
            mgr.send_message = original

        assert r.status_code == 200, f"{r.status_code} {r.text[:120]}"
        assert calls["send"] == [("kai", "feishu")], f"agent 维度没传下去或传错：{calls['send']}"

    def testAbsentAgentIsNotFoundNotSilentlyDefault(self, twoAgents):
        """点名一个没配的 agent ⇒ 404，不能被 default 那只顶掉（那是 §6-189 同一种静默错投）。"""
        client, mgr, calls = twoAgents
        r = client.get(f"{ADAPTER_PREFIX}/feishu", params={"agent_id": "nobody"})

        assert r.status_code == 404, f"不存在的 agent 拿到了 {r.status_code}"
        assert calls["status"] == [], f"却去打了一只实例：{calls['status']}"

    def testDefaultRemainsTheFallbackWhenParamOmitted(self, twoAgents):
        """对照：不带 `agent_id` 时仍走 default——既有调用者一字不变。"""
        client, mgr, calls = twoAgents
        r = client.get(f"{ADAPTER_PREFIX}/feishu")

        assert r.status_code == 200
        assert calls["status"] == ["default"], f"缺省行为被改了：{calls['status']}"


class TestHealthSweepCoversEveryAgentInstance:
    def testListChannelsIncludesNonDefaultInstance(self, twoAgents):
        client, mgr, _calls = twoAgents
        r = client.get(ADAPTER_PREFIX)

        assert r.status_code == 200
        adapters = r.json().get("adapters") or {}
        assert any("kai" in key for key in adapters), (
            f"非 default 的实例在列表里根本不存在（键={sorted(adapters)}）")

    def testHealthAllAndListChannelsShareOneFace(self, twoAgents):
        """两个端点都读同一份健康视图；键约定也只许有一份实现（default 裸键向后兼容）。"""
        client, mgr, _calls = twoAgents
        listed = client.get(ADAPTER_PREFIX).json().get("adapters") or {}
        healthAll = client.get(f"{ADAPTER_PREFIX}/health/all").json().get("adapters") or {}

        assert set(listed) == set(healthAll), (
            f"两个端点的定义域不一致：{sorted(set(listed) ^ set(healthAll))}")
        assert "feishu" in listed, f"default 的裸键丢了（向后兼容被破坏）：{sorted(listed)}"

    def testViewKeyConventionHasOneImplementation(self):
        """键约定只许有一份：两份视图各自内联一遍，加维度时必然只改到一处。"""
        src = (REPO / "neurova" / "channels" / "manager.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        defs = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_adapterViewKey"]
        assert len(defs) == 1, f"`_adapterViewKey` 定义了 {len(defs)} 次"
        users = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = [c for c in ast.walk(node)
                         if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                         and c.func.id == "_adapterViewKey"]
                if inner and node.name != "_adapterViewKey":
                    users.add(node.name)
        assert {"list_adapters", "health_check"} <= users, (
            f"两份视图没共用键约定（用了它的是 {sorted(users)}）")


class TestTheSecondReplaceFaceIsGone:
    def testReplaceChannelRetiredAndUnreferenced(self):
        assert not hasattr(ChannelManager, "replace_channel"), (
            "`replace_channel` 还在：它与 channel_config 保存路径那份构成第二实现")
        own = pathlib.Path(__file__).resolve()
        for rel in ("neurova", "tests"):
            for path in sorted((REPO / rel).rglob("*.py")):
                if "__pycache__" in path.parts or path.resolve() == own:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                assert ".replace_channel(" not in text, f"{path} 还在调那份死面"

    def testLiveReplacementFaceStillDoesTheJob(self):
        """退役的凭据是"另一份在做且更完整"，不是"没人调所以删"——现读保存路径那一份的证据。"""
        src = (REPO / "neurova" / "api" / "endpoints" / "channel_config.py").read_text(encoding="utf-8")
        for mark in ("get_adapter(request.channel_type, agent_id=agent_id)",
                     "unregister_adapter(request.channel_type, agent_id=agent_id)",
                     "register_adapter(adapter, agent_id=agent_id)",
                     "await adapter.connect()"):
            assert mark in src, f"现役替代那份少了这一步：{mark}"
