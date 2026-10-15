# -*- coding: utf-8 -*-
"""环节轴并进 `capability_gap` 单源，且两族用途不许混（ModularRSI 对照 §7.1-Q4 甲案）。

## 为什么扩这一族

原判据口径写的是"信号有界三条，不扩面"（T-03 立模块时）。而"改哪个环节"这件事在本仓
没有单源：`self_model` 五算子回答"谁在失败"、`FailurePattern` 六桶回答"什么错误类型"、
`capability_gap` 三值回答"缺哪项能力"。再造一套环节枚举就是第三套分类（教义第 7 条禁止）。
比后合的结论是：环节证据落在 `capability_gap` 这份单源上扩一族，而不是新造枚举。

## 这条链上最容易出的错，也是本守卫的靶

`chat_pipeline._check_nl_synthesis` 此前吃 `gap.hasGap` —— 一旦"假完成/环停滞"进了同一
收件箱，`hasGap` 就为真，于是**环推不完会被当成"缺一条工具"**去驱动自主合成，
产出一堆没人用的工具（正是本仓一路在拆的"入口对错的东西敏感"）。所以：

- 用途在 `_GAP_PURPOSE` **单源**登记，消费方按族取用，不许各自再判一遍；
- 自主创建的入口只看 `capabilityKinds`；
- 门控（`agent/gates.py`）保持纯判定，投递只发生在环出口求值点——
  在 `check()` 里写副作用会让"门控能不能被单测/能不能复用"两件事一起坏掉。

## 判据八格

1-2 词表单源与两族派生（并集=全表、交集为空、每条都登记了用途）；
3 新 kind 投得进收件箱（`recordCapabilityGap` 不再拒收）；
4 harness 族单独命中时 `capabilityKinds` 必须为空（这条就是上面那个错的正面判据）；
5 出口投递助手按门名分流，且"目标已达成"不投；
6 合成入口真的按 `capabilityKinds` 把关（钉代码形态，不钉日志措辞）；
7 门控模块里不得出现缺口投递调用（副作用不许长在纯判定里）；
8 观测面写读闭环：新 kind 进 `gapMetricReadout()` 的 by_kind。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATES_PY = PROJECT_ROOT / "neurova" / "agent" / "gates.py"
CHAT_PIPELINE_PY = PROJECT_ROOT / "neurova" / "agent" / "chat_pipeline.py"

CAPABILITY_KINDS = {"attachment_unreadable", "repeated_tool_failure", "catalog_miss"}
HARNESS_KINDS = {"false_completion", "loop_stalled"}


@pytest.fixture(autouse=True)
def _freshInbox():
    from neurova.agent.capability_gap import clearCapabilityGap

    clearCapabilityGap()
    yield
    clearCapabilityGap()


class TestGapVocabularyIsSingleSourced:
    def test_1_kindsComeFromOnePurposeTable(self):
        from neurova.agent import capability_gap as gap

        assert set(gap.GAP_KINDS) == CAPABILITY_KINDS | HARNESS_KINDS, (
            f"单源名单与预期两族不等：{set(gap.GAP_KINDS)}"
        )
        assert set(gap.CAPABILITY_GAP_KINDS) == CAPABILITY_KINDS
        assert set(gap.HARNESS_GAP_KINDS) == HARNESS_KINDS
        assert not (set(gap.CAPABILITY_GAP_KINDS) & set(gap.HARNESS_GAP_KINDS)), (
            "两族有交集就是用途没定清")
        assert set(gap._GAP_PURPOSE) == set(gap.GAP_KINDS), (
            "有 kind 没登记用途——消费方只能各自猜，那正是第二份定义的起点")
        assert set(gap._GAP_PURPOSE.values()) == {"capability", "harness"}

    def test_2_derivedFromTableNotHandCopied(self):
        """两族名单必须是从用途表派生的，不是又抄一遍字面量。"""
        src = (PROJECT_ROOT / "neurova" / "agent" / "capability_gap.py").read_text(encoding="utf-8")
        for literal in ('CAPABILITY_GAP_KINDS = ("attachment_unreadable"',
                        'HARNESS_GAP_KINDS = ("false_completion"'):
            assert literal not in src, f"派生名单被改回字面量手抄：{literal}"

    def test_3_harnessKindsAreAcceptedByTheRecorder(self):
        from neurova.agent.capability_gap import (
            GAP_FALSE_COMPLETION, GAP_LOOP_STALLED, detectCapabilityGap, recordCapabilityGap)

        recordCapabilityGap(GAP_FALSE_COMPLETION, {"gate": "goal"})
        recordCapabilityGap(GAP_LOOP_STALLED, {"gate": "doom_loop"})
        verdict = detectCapabilityGap()
        assert {GAP_FALSE_COMPLETION, GAP_LOOP_STALLED} <= set(verdict.kinds), (
            f"harness 族被拒收：{verdict.kinds}")


class TestPurposeIsolation:
    def test_4_harnessOnlyGapMustNotLookLikeAMissingCapability(self):
        from neurova.agent.capability_gap import (
            GAP_FALSE_COMPLETION, detectCapabilityGap, recordCapabilityGap)

        recordCapabilityGap(GAP_FALSE_COMPLETION, {"gate": "goal"})
        verdict = detectCapabilityGap()
        assert verdict.hasGap is True, "本轮确实有缺口，hasGap 该为真"
        assert verdict.capabilityKinds == [], (
            f"环走不动被判成了'缺能力'：{verdict.capabilityKinds}")
        assert verdict.harnessKinds == [GAP_FALSE_COMPLETION]

    def test_5_exitHelperRoutesByGateName(self):
        from neurova.agent.capability_gap import (
            GAP_FALSE_COMPLETION, GAP_LOOP_STALLED, detectCapabilityGap)
        from neurova.agent.loops.base import _recordHarnessGapFromExit

        _recordHarnessGapFromExit("goal", achieved=False, reason="模型自认完成但目标未达成")
        assert detectCapabilityGap().harnessKinds == [GAP_FALSE_COMPLETION]

        _recordHarnessGapFromExit("iteration", achieved=False, reason="轮次上限")
        assert detectCapabilityGap().harnessKinds == [GAP_LOOP_STALLED]

        _recordHarnessGapFromExit("token_budget", achieved=False)
        assert detectCapabilityGap().harnessKinds == [GAP_LOOP_STALLED]

        # 目标已达成是正常收口，不是缺口
        _recordHarnessGapFromExit("goal", achieved=True)
        _recordHarnessGapFromExit("some_other_gate", achieved=False)
        assert detectCapabilityGap().hasGap is False, "不该投的地方投了"

    def test_6_synthesisEntryGatesOnCapabilityKindsOnly(self):
        """钉代码形态：自主创建的入口判 `capabilityKinds`，不再判 `hasGap`。"""
        tree = ast.parse(CHAT_PIPELINE_PY.read_text(encoding="utf-8"))
        target = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "_check_nl_synthesis"),
            None)
        assert target is not None, "找不到 _check_nl_synthesis——本判据的扫描面变了，须改判而非放过"
        body = ast.unparse(target)
        assert "capabilityKinds" in body, "合成入口没按族把关"
        assert "not gap.hasGap" not in body, "入口仍在用 hasGap——harness 族会误驱动自主创建"

    def test_7_pureGatesStaySideEffectFree(self):
        tree = ast.parse(GATES_PY.read_text(encoding="utf-8"))
        offenders = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (getattr(node.func, "id", getattr(node.func, "attr", ""))
                 in {"recordCapabilityGap", "_recordHarnessGapFromExit"})
        ]
        assert not offenders, f"门控里出现投递调用 {offenders}——副作用不许长在纯判定里"

    def test_8_metricsReadoutSeesTheNewKinds(self):
        from neurova.agent.capability_gap import (
            GAP_LOOP_STALLED, gapMetricReadout, recordGapMetrics)

        before = gapMetricReadout().get("by_kind", {}).get(GAP_LOOP_STALLED, 0)
        recordGapMetrics([GAP_LOOP_STALLED])
        after = gapMetricReadout().get("by_kind", {}).get(GAP_LOOP_STALLED, 0)
        assert after == before + 1, (
            f"只写不读的观测面：写后读数 {before}→{after}（读侧没接上就是断点）")
