# -*- coding: utf-8 -*-
"""T-06b · 观察预算裁剪必须量化上报，且两后端同一形状。

## 病灶（2026-09-30 活体量出，见工单集 §5.6 ④）

给 `browser_dom_snapshot` 显式 `max_nodes`/`max_depth` 时，MDN 一页从 191 行被裁到
15 行、深度从 10 压到 2，而响应里 `truncated` 与计数字段**全是 None**——模型以为
看到的 15 行就是页面全部。

三条独立缺陷，同一根因（感知预算的执行与上报没有单源）：

| 缺陷 | Playwright 后端 | camofox 后端 |
|---|---|---|
| 预算裁剪上报 | `_trim_snapshot_tree` 第二返回值**直接丢弃**（`browser_manager.py:472`） | 只并入一个布尔，且藏在 `data` 里（`camofox_server_backend.py:302`） |
| 上报形状 | 无 | `data["truncated"]`（dict 载荷） |
| 字符预算是否生效 | 生效 | **整条绕过**——执行器只处理 `isinstance(data, str)`，camofox 的 `data` 是 dict |

camofox 在启用时是**首选路由**（`browser_manager.py:1057` 先于 playwright 判定），
不是 dormant 兜底，所以第三条是活路不是死路。

## 判据取向

只回布尔不够（T-06 已确立）：要回"裁了多少行、其中多少是可交互项"。
计数口径与字符折叠共用同一份可交互 role 单源，不另造一套。
"""

from __future__ import annotations

import pytest

from neurova.computer_use.browser_manager import (
    BrowserResult,
    applySnapshotBudget,
)

# 已知形状：1 个 document + 2 个容器 + 12 个可交互 link（各带一行 /url 子节点）
TREE = "\n".join(
    ["- document:", "  - navigation:"]
    + [f'    - link "导航{j}"' for j in range(2)]
    + ["  - main:"]
    + [f'    - link "条目{j}":' for j in range(10)]
    + [f'      - /url: "#x{j}"' for j in range(10)]
)


def _actionables(text: str) -> int:
    from neurova.computer_use.browser_manager import _ariaRoleToken, _snapshotActionableRoles

    roles = _snapshotActionableRoles()
    return sum(1 for ln in text.splitlines() if _ariaRoleToken(ln) in roles)


class TestBudgetReportsQuantities:
    def test_noBudgetPassesThroughSilently(self):
        out = applySnapshotBudget(TREE, None, None)
        assert out.text == TREE
        assert out.truncated is False
        assert out.hiddenNodes == 0 and out.hiddenActionable == 0

    def test_budgetThatDoesNotBiteIsNotReportedAsTruncated(self):
        out = applySnapshotBudget(TREE, max_nodes=9999, max_depth=99)
        assert out.truncated is False
        assert out.hiddenNodes == 0

    def test_nodeBudgetReportsHiddenLineCount(self):
        out = applySnapshotBudget(TREE, max_nodes=6, max_depth=None)
        total = len(TREE.splitlines())
        assert out.truncated is True
        assert len(out.text.splitlines()) == 6
        assert out.hiddenNodes == total - 6

    def test_depthBudgetReportsHiddenActionableCount(self):
        """深度裁剪最狠：整棵子树消失，可交互项成片不见——必须报出数量。"""
        out = applySnapshotBudget(TREE, None, 2)
        assert out.truncated is True
        assert _actionables(out.text) < _actionables(TREE)
        assert out.hiddenActionable == _actionables(TREE) - _actionables(out.text)
        assert out.hiddenActionable > 0


class TestBothBackendsReportIdentically:
    """两后端同一承载：形状分叉就是判据分叉（T-03 同族教训）。"""

    @staticmethod
    async def _playwrightResult(maxNodes):
        import neurova.computer_use.browser_manager as bmm

        page = _FakePage(TREE)
        be = bmm.PlaywrightBackend({"headless": True})
        be._initialized = True
        # _page 是只读属性，由活动 tab 派生 ⇒ 夹具登记 tab，不去赋值页面
        be._register_tab(page)
        be._tabs[be._active_target_id]["generation"] = 3
        return await be.dom_snapshot(None, maxNodes, None)

    @staticmethod
    async def _camofoxResult(maxNodes):
        from tests.unit.computer_use.test_camofox_server_backend import (
            _http_response,
            _make_backend,
            _seed_tab,
        )

        b, _client = _make_backend(
            request_return=_http_response({"snapshot": TREE, "refsCount": 12, "url": "https://x"}),
        )
        _seed_tab(b)
        return await b.dom_snapshot(None, maxNodes, None)

    @pytest.mark.asyncio
    async def test_bothBackendsCarryBudgetFields(self):
        for make in (self._playwrightResult, self._camofoxResult):
            res = await make(6)
            assert res.truncated is True, "预算裁剪未上报"
            assert res.hiddenNodes > 0, "只回布尔不够——要回裁掉的行数"
            assert res.hiddenActionable >= 0

    @pytest.mark.asyncio
    async def test_bothBackendsEmitSameResultKeys(self):
        p = (await self._playwrightResult(6)).to_dict()
        c = (await self._camofoxResult(6)).to_dict()
        shared = {"truncated", "hiddenNodes", "hiddenActionable"}
        assert shared <= set(p) and shared <= set(c), (
            f"承载字段两后端不齐：playwright={sorted(set(p) & shared)} camofox={sorted(set(c) & shared)}"
        )

    @pytest.mark.asyncio
    async def test_underBudgetResultCarriesNoNoise(self):
        res = await self._playwrightResult(None)
        d = res.to_dict()
        assert "hiddenNodes" not in d or d.get("hiddenNodes") == 0
        assert d.get("truncated") in (None, False)


class TestExecutorAppliesCharBudgetOnBothPayloadShapes:
    """camofox 的 dict 载荷整条绕过字符预算——这是活路不是死路。"""

    @staticmethod
    def _hugeTree() -> str:
        lines = ["- document:", "  - main:"]
        for i in range(600):
            lines.append(f'    - link "长条目 {i}":')
            lines.append(f'      - /url: "/p/{i}"')
        return "\n".join(lines)

    @pytest.mark.asyncio
    async def test_camofoxDictPayloadGetsFolded(self, monkeypatch):
        import asyncio

        from neurova.tool_executor import ToolExecutor
        import neurova.computer_use as cu

        huge = self._hugeTree()

        class M:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                return BrowserResult(success=True, data={"snapshot": huge, "refs_count": 600,
                                                         "truncated": False})

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: M())
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()
        r = await inst._execute_browser_dom_snapshot({})
        payload = r["data"]
        inner = payload["snapshot"] if isinstance(payload, dict) else payload
        assert len(inner) <= 8000 + 512, "camofox 载荷整条绕过字符预算"
        assert "/folded" in inner

    @pytest.mark.asyncio
    async def test_budgetCountsReachModelVisibleResult(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor
        import neurova.computer_use as cu

        class M:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                return BrowserResult(success=True, data=TREE, truncated=True,
                                     hiddenNodes=7, hiddenActionable=5)

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: M())
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()
        r = await inst._execute_browser_dom_snapshot({"max_nodes": 12})
        assert r.get("truncated") is True
        assert r.get("hiddenNodes") == 7 and r.get("hiddenActionable") == 5


class _FakePage:
    """真数据假驱动：只提供 aria 文本，判据打的是我们自己的预算与上报代码。"""

    def __init__(self, tree: str):
        self.url = "http://fake/"
        self._tree = tree

    def locator(self, _selector):
        page = self

        class _L:
            async def aria_snapshot(self):
                return page._tree

        return _L()

    async def title(self):
        return "fake"

    async def content(self):
        return "<html></html>"

    async def evaluate(self, *_a):
        return 1080
