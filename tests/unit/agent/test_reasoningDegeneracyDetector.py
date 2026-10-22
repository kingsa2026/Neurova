# -*- coding: utf-8 -*-
"""思考流退化判据的单源规格（`reasoning_degeneracy` 那一份实现）。

为什么判据必须只有一份：`OpenAILoop` 流式、`AnthropicLoop` 流式、非流式存储三处都要认
"这一段思考作废了"。三处各拼一遍正则，就又是"某条环的守卫恒不触发"（与 §6-77 的 usage
归一同形：读了不写/写了不读的第三种形态——三处判据漂移）。

口径：文本**尾部**一段由单一短单元连发构成的重复区，长度达到阈值即判退化；
返回重复单元与重复区起点，起点之前是还能看的思考。
"""
from __future__ import annotations

import pytest

from neurova.agent.loops.reasoning_degeneracy import (
    MAX_DEGENERACY_PERIOD,
    MIN_DEGENERACY_CHARS,
    findDegeneracy,
    stripDegeneracy,
)


def aboveWindow(unit: str) -> int:
    """连发到刚越过阈值线所需的次数。"""
    return (MIN_DEGENERACY_CHARS // len(unit)) + 5


def belowWindow(unit: str) -> int:
    """仍在阈值窗口之下的次数。"""
    return max(1, (MIN_DEGENERACY_CHARS // len(unit)) // 2)


class TestDetectorShape:
    def testDetectsSingleTokenCollapse(self):
        """事故本体：4 字符单元连发到吃满预算。"""
        text = "lock" * aboveWindow("lock")
        found = findDegeneracy(text)
        assert found is not None, "尾部短单元连发超阈值必须判退化"
        assert found.unit == "lock", found.unit
        assert found.start == 0, found.start
        assert found.chars >= MIN_DEGENERACY_CHARS, found.chars

    def testShortestPeriodWins(self):
        """同一串连发要报最小单元：报「locklock」会把点名的内容写成假事实。"""
        found = findDegeneracy("lock" * aboveWindow("lock"))
        assert found is not None and found.unit == "lock", found

    def testStartAnchorsAtTheCollapseRun(self):
        """退化前常有正常思考：起点落在连发段开头，前面那段才留得下来。"""
        legit = "先查任务计划，再并行检索记忆与工作目录，整体判断如下："
        found = findDegeneracy(legit + "lock" * aboveWindow("lock"))
        assert found is not None and found.start == len(legit), (found.start, len(legit))
        clean, degeneracy = stripDegeneracy(legit + "lock" * aboveWindow("lock"))
        assert degeneracy is not None and clean == legit, repr(clean)

    def testNothingBelowWindow(self):
        assert findDegeneracy("lock" * belowWindow("lock")) is None

    def testNothingWhenTailIsNotPeriodic(self):
        """长而不周期：逐步展开的推理不得被误杀。"""
        text = "".join(f"第{i}步：检查上一轮结果并决定下一个工具。" for i in range(400))
        assert findDegeneracy(text) is None

    def testNothingWhenUnitExceedsPeriodCap(self):
        """周期单元超过上限 ⇒ 那是段落在自我复述，不是 token 级退化。"""
        unit = "".join(f"步骤{i}：" for i in range(9))  # 36 字符、内部不周期
        assert len(unit) > MAX_DEGENERACY_PERIOD, len(unit)
        assert findDegeneracy(unit * (MIN_DEGENERACY_CHARS // len(unit) + 3)) is None

    def testEmptyAndShortTextAreQuiet(self):
        assert findDegeneracy("") is None
        assert findDegeneracy("嗯") is None

    def testStripIsNoOpOnCleanText(self):
        clean = "正常的一段思考过程，没有任何连发。"
        text, found = stripDegeneracy(clean)
        assert text == clean and found is None


class TestThresholdsAreSane:
    def testWindowIsAboveAnyHonestThoughtFragment(self):
        """阈值窗口要显著大于正常思考里会出现的重复（"----" 分隔线、省略号），
        也要显著小于事故那次的 16384 字符——否则这次拦住不了事故。"""
        assert MIN_DEGENERACY_CHARS >= 1024
        assert MIN_DEGENERACY_CHARS < 16384
        assert 1 < MAX_DEGENERACY_PERIOD < MIN_DEGENERACY_CHARS
