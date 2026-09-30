# -*- coding: utf-8 -*-
"""快照折叠替代头部硬切（工单集 T-06 前置）。

## 病灶（亲验）

`tool_executor.py` 对 `browser_dom_snapshot` 的 `data` 做 `data[:8000] + "…[已截断]"`
——**只保头部**。真机量测（2026-09-30，10 页）：3/10 页触发，触发时被切掉的是全文的
80.8%–95.4%，其中**可交互元素损失 81.1%–93.1%**；而保留下来的前缀在结构上就是页头导航
那批 chrome，正文里的按钮/链接/输入框整段静默消失。

本仓回环处 `neurova/core/tool_offload.py::_head_tail_preview` 的注释已经把折叠教义写死了：
"中段以省略行**显式计数**，绝不静默消失"。头部硬切违反的正是这条自订判据——它既不留尾、
也不报数。

## 两个被取证推翻的设计（写在案发现场，防止后来者重犯）

1. **"折掉枝叶、留全部可交互骨架"被否证**：把非可交互且非可交互祖先的行全折掉后，
   剩下的可交互骨架本身仍是 8000 预算的 254% / 1045% / 1087%。超限页的问题是
   **可交互面本身就装不下**，不是枝叶挤占。
2. **"按区带等距取样"也被否证**（首版实现就是这么写的，活体读数打脸）：真实页面的
   区带极碎——MDN 一页 **566 个区带、最大区带仅 9 项**，"每区带留 1 个样本"本身就超预算，
   于是永远掉进全局兜底，可交互项 0 个来自切点之后。所以取样必须是**跨全树全局等距**。
   首版夹具用的是"1 个区带 1600 项"，那是按缺陷叙事造的、不具代表性；本文件的**主夹具
   `_realShapeTree` 按实测分布造**，`_bigTree` 降为区带内取样能力的专项夹具。

## 边界

`browser_extract_text` 的正文不是树、无可折结构，本单不动它（其上报口径归 T-06）。
"""

from __future__ import annotations

import pytest

from neurova.computer_use.browser_manager import (
    SNAPSHOT_CONTEXT_BUDGET,
    foldSnapshotTree,
)

# 可交互 role 口径与实现侧一致：折叠标记行不得被算成一个元素
_ACTIONABLE_ROLES = {"button", "link", "textbox", "checkbox", "searchbox", "tab"}


def _region(title: str, count: int, start: int, role: str = "link") -> list:
    """造一个区带：容器行 + count 个可交互子项（名字唯一，便于定位尾项）。"""
    lines = [f"  - main \"{title}\":"]
    for i in range(start, start + count):
        lines.append(f'    - {role} "条目{title}{i}":')
        lines.append(f'      - /url: "#x{i}"')
    return lines


def _bigTree(tailCount: int = 1600) -> str:
    """单一巨型区带形态：可交互项全挤在一个容器里。

    只用于验证"区带内也要等距取样"这条能力，**不是**真实页面的形状。
    """
    head = [
        "- document:",
        "  - banner:",
    ] + [f'    - link "导航{j}"' for j in range(8)]
    return "\n".join(head + _region("正文", tailCount, start=0))


def _realShapeTree(regions: int = 520) -> str:
    """主夹具：按活体取证到的真实形状造（数百个小区带，可交互项稀薄且大半在切点后）。"""
    lines = ["- document:", "  - banner:"]
    lines += [f'    - link "顶部导航{j}"' for j in range(6)]
    lines.append("  - main:")
    for r in range(regions):
        lines.append(f'    - listitem "分组 {r}":')
        lines.append(f"      - paragraph: 第 {r} 段说明文字，用于撑出真实页面的嵌套形状。")
        lines.append(f'      - link "内容链接 {r}":')
        lines.append(f'        - /url: "/section/{r}"')
    return "\n".join(lines)


def _roleToken(line: str):
    s = line.strip()
    if not s.startswith("- "):
        return None
    s = s[2:]
    token = ""
    for ch in s:
        if ch in ' "\'[':
            break
        token += ch
    return token.lower().rstrip(":") or None


def _actionableLines(text: str) -> list:
    return [ln for ln in text.splitlines() if _roleToken(ln) in _ACTIONABLE_ROLES]


def _beyondCut(lines, tree):
    """按**原始字符偏移**判定是否落在切点之后（字符串包含会被重名行骗过）。"""
    offsets, acc = [], 0
    for ln in tree.splitlines():
        offsets.append(acc)
        acc += len(ln) + 1
    order = [i for i, ln in enumerate(tree.splitlines()) if _roleToken(ln) in _ACTIONABLE_ROLES]
    cursor = {}
    keptOffsets = []
    byText = {}
    for idx, i in enumerate(order):
        byText.setdefault(tree.splitlines()[i].strip(), []).append(offsets[i])
    for ln in lines:
        key = ln.strip()
        if key not in byText:
            continue
        used = cursor.get(key, 0)
        if used < len(byText[key]):
            keptOffsets.append(byText[key][used])
            cursor[key] = used + 1
    return [o for o in keptOffsets if o > SNAPSHOT_CONTEXT_BUDGET], keptOffsets


class TestFixtureIsNotVacuous:
    """夹具防空转：本文件所有判据都建立在"确实超限且形状真实"之上。"""

    def test_fixtureReallyOverBudget(self):
        tree = _realShapeTree()
        assert len(tree) > SNAPSHOT_CONTEXT_BUDGET * 4, (
            f"夹具仅 {len(tree)} 字符，未超预算——本文件判据会集体空转"
        )

    def test_mostActionableFactsLieBeyondTheChopPoint(self):
        """复刻真机量测的形状：可交互事实的绝大多数落在切点之后。"""
        tree = _realShapeTree()
        allAct = _actionableLines(tree)
        beyond, _ = _beyondCut(allAct, tree)
        assert len(beyond) >= len(allAct) * 0.7, (
            f"仅 {len(beyond)}/{len(allAct)} 可交互事实落在切点之后，夹具不具代表性"
        )

    def test_fixtureRegionsAreFragmentedLikeRealPages(self):
        """真实页面区带极碎（MDN 实测 566 个区带、最大 9 项）——
        这条钉住夹具形状，防止后来者把夹具改回"单一大区带"从而让判据集体失效。"""
        tree = _realShapeTree()
        perRegion = {}
        indentOf = [len(ln) - len(ln.lstrip()) for ln in tree.splitlines()]
        stack, parent = [], []
        for i, ind in enumerate(indentOf):
            while stack and stack[-1][0] >= ind:
                stack.pop()
            parent.append(stack[-1][1] if stack else -1)
            stack.append((ind, i))
        for i, ln in enumerate(tree.splitlines()):
            if _roleToken(ln) in _ACTIONABLE_ROLES:
                perRegion[parent[i]] = perRegion.get(parent[i], 0) + 1
        assert len(perRegion) > 300, f"区带数 {len(perRegion)}，不像真实页面的碎形状"
        assert max(perRegion.values()) <= 12, "存在巨型区带，夹具退化成不真实形状"


class TestFoldFitsBudget:
    def test_overBudgetTreeFoldsWithinBudget(self):
        tree = _realShapeTree()
        fold = foldSnapshotTree(tree)
        folded, hidden, didFold = fold.text, fold.hiddenCount, fold.didFold
        assert didFold is True
        assert len(folded) <= SNAPSHOT_CONTEXT_BUDGET

    def test_underBudgetTreePassesThroughUntouched(self):
        tree = "- document:\n  - button \"登录\"\n  - link \"帮助\""
        fold = foldSnapshotTree(tree)
        folded, hidden, didFold = fold.text, fold.hiddenCount, fold.didFold
        assert folded == tree
        assert didFold is False
        assert hidden == 0

    def test_emptyTreeIsNotFolded(self):
        fold = foldSnapshotTree("")
        assert (fold.text, fold.hiddenCount, fold.didFold) == ("", 0, False)
        assert fold.charsTotal == 0 and fold.actionableTotal == 0


class TestTailStaysRepresented:
    """本单的核心行为：折叠必须覆盖切点之后，而不是换个说法继续只留头部。"""

    def test_foldKeepsActionableSampleFromTailRegion(self):
        tree = _realShapeTree()
        folded = foldSnapshotTree(tree).text
        beyond, _ = _beyondCut(_actionableLines(folded), tree)
        assert beyond, "尾部区带的可交互事实被整段静默丢弃，折叠没有生效"

    def test_foldSpreadsAcrossTheWholeTreeNotJustPastTheCut(self):
        """取样要真正走到底：保留项的原始偏移最大值必须接近树尾。"""
        tree = _realShapeTree()
        folded = foldSnapshotTree(tree).text
        _, kept = _beyondCut(_actionableLines(folded), tree)
        assert kept, "折叠后没有留下任何可交互项"
        lastOffset = len(tree) - len(tree.splitlines()[-1])
        assert max(kept) > lastOffset * 0.8, (
            f"保留项最深只到 {max(kept)}/{lastOffset}，没有覆盖到树尾"
        )

    def test_foldAnnouncesHiddenCount(self):
        tree = _realShapeTree()
        fold = foldSnapshotTree(tree)
        hidden, didFold = fold.hiddenCount, fold.didFold
        total = len(_actionableLines(tree))
        assert didFold is True
        assert hidden > 0
        assert hidden < total, "全折光等于没折——必须留样本"

    def test_foldedMarkerLineReportsCountsNotJustEllipsis(self):
        """藏起来的部分要留下可读痕迹（本仓 _head_tail_preview 同一口径）。"""
        fold = foldSnapshotTree(_realShapeTree())
        folded, hidden, didFold = fold.text, fold.hiddenCount, fold.didFold
        assert didFold is True
        marker = [ln for ln in folded.splitlines() if "/folded" in ln]
        assert marker, "没有任何显式计数行——被折事实仍然静默消失"
        assert str(hidden) in "".join(marker), f"计数行未如实报出被折项数 {hidden}"

    def test_withinRegionSamplingOnOneHugeRegion(self):
        """专项：单一大区带内部也必须等距取样，不能只取区带头部（旧 _bigTree 形状）。"""
        tree = _bigTree()
        folded = foldSnapshotTree(tree).text
        beyond, _ = _beyondCut(_actionableLines(folded), tree)
        assert len(beyond) >= 3, "单一巨型区带内没有做等距取样"


    def test_foldKeepsDirectParentAsSemanticAnchor(self):
        """祖先深度封到 1 层不能把直接父行也封掉 —— 模型需要知道元素出自哪个区带。"""
        import re

        tree = _realShapeTree()
        folded = foldSnapshotTree(tree).text
        kept = _actionableLines(folded)
        assert kept, "折叠后没有留下元素，锚点判据不得靠空集合蒙过"
        anchored = 0
        for ln in kept:
            m = re.search(r'内容链接 (\d+)', ln)
            if m:
                assert f'listitem "分组 {m.group(1)}"' in folded, (
                    f"保留的链接「{m.group(1)}」失去了直接父行，元素变得无上下文可依"
                )
                anchored += 1
        assert anchored > 0


class TestFoldMarkerIsNotAddressable:
    def test_foldedMarkerIsNotCountedAsAnElement(self):
        """折叠标记不得被 role 解析当成正经元素，否则模型会去点它、计数也会虚增。"""
        fold = foldSnapshotTree(_realShapeTree())
        folded, didFold = fold.text, fold.didFold
        assert didFold is True
        marker = [ln for ln in folded.splitlines() if "/folded" in ln]
        assert marker, "无折叠标记，本判据不得靠'循环体没执行'蒙过"
        for ln in marker:
            assert _roleToken(ln) not in _ACTIONABLE_ROLES

    def test_foldDoesNotFabricateElements(self):
        """折叠后的可交互项必须都是原树里真实存在的行，不得凭空生成。"""
        tree = _realShapeTree()
        folded = foldSnapshotTree(tree).text
        kept = _actionableLines(folded)
        assert kept, "折叠后一个可交互元素都不剩，'未凭空生成'不得靠空集合蒙过"
        original = {ln.strip() for ln in _actionableLines(tree)}
        for ln in kept:
            assert ln.strip() in original, f"折叠产物出现原树没有的元素行：{ln.strip()}"


class TestGuardIsNotVacuous:
    """反向控制：拿旧行为（头部硬切）喂同一夹具，判据必须红。"""

    def test_headChopLeavesNoTailCoverage(self):
        tree = _realShapeTree()
        chopped = tree[:SNAPSHOT_CONTEXT_BUDGET] + "…[已截断]"
        assert len(chopped) <= SNAPSHOT_CONTEXT_BUDGET + 10
        beyond, _ = _beyondCut(_actionableLines(chopped), tree)
        assert not beyond, "对照失效：头部硬切竟然保住了尾部样本"
        assert not any("/folded" in ln for ln in chopped.splitlines())

    def test_foldCoversTailWhileChopCoversOnlyHead(self):
        """判据不是"留下更多元素"，而是"留下的代表整页"。

        活体读数：折叠保留的元素数可以**少于**硬切（计数行与跨树取样要付预算）。
        这项数量劣势是有意接受的 —— 硬切留下的全部挤在头部前缀，模型会误以为
        页面就只有那些元素。
        """
        tree = _realShapeTree()
        folded = foldSnapshotTree(tree).text
        foldBeyond, _ = _beyondCut(_actionableLines(folded), tree)
        chopBeyond, _ = _beyondCut(_actionableLines(tree[:SNAPSHOT_CONTEXT_BUDGET]), tree)
        assert chopBeyond == [] or len(chopBeyond) == 0
        assert len(foldBeyond) > 0


class TestDeepChainFallback:
    """兜底分支：超深嵌套页里"1 个元素 + 它的整条祖先链"就塞不进预算。

    此时必须丢结构保事实（扁平可交互清单），仍附计数行 —— 绝不退化成无痕硬切。
    """

    @staticmethod
    def _deepChain(depth: int = 200, leaves: int = 300) -> str:
        lines = ["- document:"]
        for d in range(depth):
            lines.append(
                "  " * (d + 1)
                + f'- generic "第{d}层容器，属性文字写得长一些，以便让祖先链本身就把预算吃光"'
            )
        base = "  " * (depth + 1)
        for i in range(leaves):
            lines.append(f'{base}- link "深层链接 {i}"')
        return "\n".join(lines)

    def test_fallbackStillFitsBudget(self):
        tree = self._deepChain()
        assert len(tree) > SNAPSHOT_CONTEXT_BUDGET * 4
        fold = foldSnapshotTree(tree)
        folded, hidden, didFold = fold.text, fold.hiddenCount, fold.didFold
        assert didFold is True
        assert len(folded) <= SNAPSHOT_CONTEXT_BUDGET, f"兜底没守住预算：{len(folded)}"

    def test_fallbackKeepsFactsNotAncestry(self):
        """兜底保的是元素事实：一条深层链接都没留下的话，折叠就只是换了个说法的丢弃。"""
        fold = foldSnapshotTree(self._deepChain())
        folded, hidden = fold.text, fold.hiddenCount
        assert _actionableLines(folded), "兜底把元素事实也丢光了"
        assert hidden > 0

    def test_fallbackDisclosesWhatItDropped(self):
        """兜底也必须留计数行——否则"绝不静默消失"这条本仓自订判据就断了。"""
        fold = foldSnapshotTree(self._deepChain())
        folded, hidden, didFold = fold.text, fold.hiddenCount, fold.didFold
        assert didFold is True
        markers = [ln for ln in folded.splitlines() if "/folded" in ln]
        assert markers, "兜底路径没有报出被折项数"
        assert str(hidden) in "".join(markers)


class TestExecutorWiring:
    """断点检查：折叠必须接在快照的生产路径上，而不是只活在纯函数里。"""

    @pytest.mark.asyncio
    async def test_executorFoldsInsteadOfChopping(self, monkeypatch):
        from neurova.computer_use.browser_manager import BrowserResult
        from neurova.tool_executor import ToolExecutor
        import neurova.computer_use as cu

        tree = _realShapeTree()

        class FakeCUManager:
            async def browser_dom_snapshot(self, generation=None, max_nodes=None, max_depth=None):
                return BrowserResult(success=True, data=tree)

        monkeypatch.setattr(cu, "get_computer_use_manager", lambda: FakeCUManager())
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()

        result = await inst._execute_browser_dom_snapshot({})
        data = result["data"]
        assert len(data) <= SNAPSHOT_CONTEXT_BUDGET
        assert "/folded" in data, "执行路径仍在用头部硬切"
        assert not data.endswith("…[已截断]"), "旧硬切标记仍在工作"
        beyond, _ = _beyondCut(_actionableLines(data), tree)
        assert beyond, "执行路径的折叠没有覆盖到切点之后"
        assert result.get("foldedActionableCount"), "折叠计数未回传（只写不读即断点）"
