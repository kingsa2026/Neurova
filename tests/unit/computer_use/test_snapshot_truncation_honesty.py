# -*- coding: utf-8 -*-
"""T-06 · 折叠后的诚实上报与补救路由。

前置：`test_snapshot_fold_replaces_chop.py` 已把头部硬切换成跨全树等距折叠。
本单管的是折叠**发生后模型知道什么**。

## 三条真缺陷

1. **规模不报**：折叠只留一个布尔 `truncated`。活体读数下模型看不到"全树多大、
   共有多少可交互项、被折几条"，于是会把"看到 50 条链接"误当成"页面只有 50 条"。
2. **路由不落地**：`browser_dom_read`（分片续读全文）早就在仓里，
   `browser_extract_text` 的描述也已经指向它，只有 `browser_dom_snapshot` 一侧
   既没在正文里给补救指引、也没在工具描述里说明——能力写了没接进反馈环，
   是 `AGENTS.md` 意义上的断点。
3. **指引可能是幻影**：正文里让模型"改用某工具"，那个工具名必须真的存在且有执行分支。
   本仓已有先例（幻影参数 `max_marks`）——**广告给模型的每个名字都得有人读**。

## 为什么不走 `_pending_hints`

`tool_coordinator._pending_hints` 承载的是**异步终态**（超时转后台、审批已裁决），
下一轮才 pop 出来注入。折叠是同步事实、已经在本次工具结果里，再投一份就是同一个信号
发两遍，且把协调器当垃圾桶用。本单把上报留在工具结果内。
"""

from __future__ import annotations

import re

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.computer_use.browser_manager import (
    SNAPSHOT_CONTEXT_BUDGET,
    foldSnapshotTree,
)
from neurova.tool_executor import COMPUTER_USE_TOOLS, ToolExecutor

_builtin_dispatch = ToolExecutor._builtin_dispatch

_ACTIONABLE = {"button", "link", "textbox", "checkbox", "searchbox", "tab"}


def _realShapeTree(regions: int = 520) -> str:
    lines = ["- document:", "  - banner:"]
    lines += [f'    - link "顶部导航{j}"' for j in range(6)]
    lines.append("  - main:")
    for r in range(regions):
        lines.append(f'    - listitem "分组 {r}":')
        lines.append(f"      - paragraph: 第 {r} 段说明文字。")
        lines.append(f'      - link "内容链接 {r}":')
        lines.append(f'        - /url: "/section/{r}"')
    return "\n".join(lines)


def _roleToken(line: str):
    s = line.strip()
    if not s.startswith("- "):
        return None
    token = ""
    for ch in s[2:]:
        if ch in ' "\'[':
            break
        token += ch
    return token.lower().rstrip(":") or None


def _actionableCount(text: str) -> int:
    return sum(1 for ln in text.splitlines() if _roleToken(ln) in _ACTIONABLE)


class TestFoldReportsScale:
    def test_foldResultCarriesScaleFields(self):
        tree = _realShapeTree()
        fold = foldSnapshotTree(tree)
        assert fold.didFold is True
        assert fold.charsTotal == len(tree)
        assert fold.actionableTotal == _actionableCount(tree)
        assert 0 < fold.hiddenCount < fold.actionableTotal
        assert len(fold.text) <= SNAPSHOT_CONTEXT_BUDGET

    def test_underBudgetFoldReportsNoFold(self):
        fold = foldSnapshotTree("- document:\n  - button \"登录\"")
        assert fold.didFold is False
        assert fold.hiddenCount == 0
        assert fold.actionableTotal == 1


class TestExecutorSurfacesScaleToModel:
    """规模字段必须进**模型可见的工具结果**，不是只活在返回值里没人读。"""

    @staticmethod
    def _drive(tree: str) -> dict:
        import asyncio

        from neurova.computer_use.browser_manager import BrowserResult
        import neurova.computer_use as cu

        class FakeCUManager:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                return BrowserResult(success=True, data=tree)

        original = getattr(cu, "get_computer_use_manager")
        cu.get_computer_use_manager = lambda: FakeCUManager()
        try:
            inst = ToolExecutor.__new__(ToolExecutor)
            inst._agent = type("A", (), {"current_session_id": None})()
            return asyncio.run(inst._execute_browser_dom_snapshot({}))
        finally:
            cu.get_computer_use_manager = original

    def test_foldedResultReportsTotalsAndHidden(self):
        tree = _realShapeTree()
        result = self._drive(tree)
        assert result.get("truncated") is True
        assert result["dataCharsTotal"] == len(tree)
        assert result["actionableCandidates"] == _actionableCount(tree)
        assert result["foldedActionableCount"] > 0
        assert result["foldedActionableCount"] < result["actionableCandidates"]

    def test_unfoldedResultStaysQuiet(self):
        """未超限就不加新字段——否则每次快照都白付上下文，是噪声不是信息。"""
        tree = "- document:\n  - button \"登录\"\n  - link \"帮助\""
        result = self._drive(tree)
        for key in ("dataCharsTotal", "actionableCandidates", "foldedActionableCount"):
            assert key not in result, f"未折叠的结果里出现了 {key}"


class TestRemedyRoutingIsNotPhantom:
    """正文里的指引必须指向真实存在的工具，且该工具有执行分支。"""

    @staticmethod
    def _namedTools(markerText: str) -> list:
        return re.findall(r"\b(browser_[a-z_]+|computer_[a-z_]+)\b", markerText)

    def test_markerNamesARealDispatchedTool(self):
        fold = foldSnapshotTree(_realShapeTree())
        markers = [ln for ln in fold.text.splitlines() if "/folded" in ln]
        assert markers
        named = self._namedTools(" ".join(markers))
        assert named, "计数行没有点名任何补救工具"
        for tool in named:
            assert tool in _BUILTIN_SCHEMAS, f"指引点名了不存在的工具：{tool}"
            assert tool in _builtin_dispatch, f"工具已声明却无执行分支：{tool}"

    def test_routingGuardIsNotVacuous(self):
        """反向控制：把幻影工具名喂进同一条判据，必须被抓出来。"""
        fake = "- /folded: 折叠 9 项；全文改用 browser_dom_som read 续读（browser_dom_read）"
        named = self._namedTools(fake)
        offenders = [t for t in named if t not in _builtin_dispatch]
        assert offenders, "判据抓不到幻影名，说明它自己就是空转的"

    def test_remedyToolIsAlsoAdvertisedInTheToolDescription(self):
        """模型在**还没被截断之前**就该知道有分片续读这条路 ——
        与 browser_extract_text 的描述口径对齐，不留两套说法。"""
        desc = _BUILTIN_SCHEMAS["browser_dom_snapshot"]["description"]
        assert "browser_dom_read" in desc, "快照工具描述没提分片续读，截断后模型无从选择"


class TestFoldMarkerStaysMachineReadable:
    def test_hiddenCountAppearsInMarkerText(self):
        fold = foldSnapshotTree(_realShapeTree())
        marker = " ".join(ln for ln in fold.text.splitlines() if "/folded" in ln)
        assert str(fold.hiddenCount) in marker, "结构化计数与正文计数不同源，必有一处说谎"

    def test_markerDisclosesElidedAncestry(self):
        """祖先深度封到 1 层后，保留行会以"无祖先的深缩进孤儿行"出现。
        层级被省略必须显式声明 —— 否则模型会把扁平正文当成页面的真实嵌套形状。"""
        fold = foldSnapshotTree(_realShapeTree())
        marker = " ".join(ln for ln in fold.text.splitlines() if "/folded" in ln)
        assert marker, "没有计数行可挂披露"
        assert "祖先" in marker, "正文省略了祖先层级却没有声明"

    def test_computerUseToolSetStillCoversSnapshotTools(self):
        """本单不新增工具名，若新增必须同步三张表 —— 这里钉住现状。"""
        for tool in ("browser_dom_snapshot", "browser_dom_read"):
            assert tool in COMPUTER_USE_TOOLS or tool in _builtin_dispatch
