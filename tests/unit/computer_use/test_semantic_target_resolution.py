# -*- coding: utf-8 -*-
"""D-6 · 语义目标解析（`smart-click` 立项的第一片）。

## 这一片交付什么、不交付什么

端点 `POST /computer/smart-click` 此前恒 501（"语义目标智能点击未实现"）。
本片接通**唯一命中即可动作**这条主路，并对多命中给出诚实拒绝——不做的事也说清楚：

- **不在本片引入 ref 寻址**。跨快照稳定句柄属 T-08，受 🔒 D-1/D-2 约束。
  本片遇到歧义时报"有哪些候选、各自 role+name"，让模型改用更具体的目标或
  `browser_dom_snapshot` + `browser_click_role`，**不赌一个**。
- 解析只在**当前快照事实**上做（aria 树的 role + accessible name），不猜 CSS 选择器——
  与本仓 `browser_dom_snapshot` 的既有纪律同向。

## 为什么"唯一命中才动作"是判据而不是保守妥协

活体取证：`get_by_role` 命中多个元素时 Playwright 直接抛
`strict mode violation: resolved to N elements`，MDN 一页 618 条可交互行去重后 429，
**56% 的行落在重名组里**。也就是说"随便取第一个"在过半场景会点错东西——
点错比不点更坏。

## 对照

归一化判据带正/负对照：大小写与全半角变体必须能命中（否则判据只是字面相等），
无关文本不得命中（否则"唯一命中"是假的）。
"""

from __future__ import annotations

import pytest

from neurova.computer_use.target_resolver import (
    Candidate,
    normalizeTarget,
    resolveTarget,
)


def _tree() -> str:
    """真 aria 行格式（与 browser_manager 的解析口径同源），不造自创语法。"""
    return "\n".join([
        "- document:",
        "  - banner:",
        '    - link "跳到主内容":',
        '      - /url: "#content"',
        '    - button "登录"',
        '    - textbox "搜索"',
        "  - main:",
        '    - button "提交订单"',
        '    - link "详情":',
        '      - /url: "/detail"',
        '    - link "详情":',
        '      - /url: "/other"',
    ])


def _candidates(tree: str) -> list:
    return [
        Candidate("link", "跳到主内容"), Candidate("button", "登录"),
        Candidate("textbox", "搜索"), Candidate("button", "提交订单"),
        Candidate("link", "详情"), Candidate("link", "详情"),
    ]


class TestNormalizationIsNotLiteralEquality:
    def test_caseAndWidthVariantsNormalize(self):
        assert normalizeTarget("  OK  ") == "ok"
        assert normalizeTarget("登录") == normalizeTarget(" 登录 ")
        # 全角 ASCII 与半角同源
        assert normalizeTarget("ＯＫ") == "ok"

    def test_unrelatedTextDoesNotCollapse(self):
        assert normalizeTarget("详情") != normalizeTarget("登录")
        # 字符顺序不同 ⇒ 不得归一到同一个（否则"唯一命中"是假的）
        assert normalizeTarget("提交订单") != normalizeTarget("订单提交")


class TestResolutionOutcomeIsThreeValued:
    def test_uniqueHitReturnsThatCandidate(self):
        out = resolveTarget("登录", _candidates(_tree()))
        assert out.state == "resolved"
        assert (out.candidate.role, out.candidate.name) == ("button", "登录")

    def test_ambiguousTargetIsReportedNotGuessed(self):
        out = resolveTarget("详情", _candidates(_tree()))
        assert out.state == "ambiguous"
        assert out.candidate is None, "歧义时绝不能替模型挑一个"
        assert len(out.candidates) == 2

    def test_noHitIsDistinguishableFromAmbiguous(self):
        out = resolveTarget("不存在的按钮", _candidates(_tree()))
        assert out.state == "unresolved"
        assert out.candidates == []

    def test_substringHitResolvesWhenUnique(self):
        """目标给的是局部说法（"订单"），只有一处包含 ⇒ 唯一命中。"""
        out = resolveTarget("订单", _candidates(_tree()))
        assert out.state == "resolved"
        assert out.candidate.name == "提交订单"

    def test_roleWordInTargetNarrowsMatch(self):
        """目标带角色词时按角色缩范围。

        注意：缩范围**不能**消解同名同角色的歧义（两个 link 详情 仍是歧义），
        它只在"同名跨角色"时把歧义变唯一——所以这里造的是 button/link 同名。
        """
        pool = [Candidate("link", "详情"), Candidate("button", "详情"), Candidate("link", "其他")]
        assert resolveTarget("详情", pool).state == "ambiguous"
        out = resolveTarget("按钮 详情", pool)
        assert out.state == "resolved"
        assert out.candidate.role == "button"
        # 同名同角色仍须报歧义，不许因为带了角色词就蒙一个
        assert resolveTarget("链接 详情", [Candidate("link", "详情"), Candidate("link", "详情")]).state == "ambiguous"


class TestResolverRunsOnRealAriaFacts:
    def test_candidatesComeFromSnapshotText(self):
        from neurova.computer_use.browser_manager import snapshotActionableCandidates

        got = snapshotActionableCandidates(_tree())
        assert [(c.role, c.name) for c in got] == [
            (c.role, c.name) for c in _candidates(_tree())
        ], "候选面必须与快照事实逐条一致，不能另解析一套"

    def test_emptyTreeYieldsNoCandidates(self):
        from neurova.computer_use.browser_manager import snapshotActionableCandidates

        assert snapshotActionableCandidates("") == []


class TestGuardIsNotVacuous:
    def test_exactOnlyMatcherWouldFailTheVariantCase(self):
        """正对照：若解析退化成字面相等，大小写/空白变体必须落空——
        说明本文件的变体判据真的在约束实现。"""
        literalOnly = [c for c in _candidates(_tree()) if c.name == "  登录 "]
        assert not literalOnly
        assert resolveTarget("  登录 ", _candidates(_tree())).state == "resolved"
