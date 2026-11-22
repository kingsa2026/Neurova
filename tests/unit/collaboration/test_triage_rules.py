"""SB-1 确定性分诊规则裁决器单测。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md §4（R0-R4 规则）
与 §8-SB-1 拆卡；阈值为原分诊门自述值（neurova/llm/triage.py:87-115）。

覆盖面：
- R0：空窗口 no_events / 最后一条是人类 human_last；
- R1：事件距离 ≤10 与时间距离 ≤300 两个 OR 分支（含人类第 8 条回归放行）；
- R2：独走环 19/20 边界（恰 19 放行、第 20 拦截、25 条全 assistant 拦截）；
- R3：6 条内 3 条重复长文本拦截、长度<8 的"好的"复读反例放行、
  本回合输入与近期 assistant 消息几乎相同拦截；
- 特征键完整性与确定性（同输入两次调用逐字段相等）；
- 时间戳不可解析不崩、退化为事件数判定；
- MAX_WINDOW=50 封顶语义。

全部用真实 dict 事件（SessionSyncManager.get_messages 形态），不用 MagicMock。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from neurova.collaboration.triage_rules import (
    AGENT_LOOP_THRESHOLD,
    HUMAN_WINDOW_EVENTS,
    HUMAN_WINDOW_SECONDS,
    MAX_WINDOW,
    REPETITION_MIN_DUPLICATES,
    REPETITION_MIN_LENGTH,
    REPETITION_WINDOW,
    SIMILARITY_THRESHOLD,
    TRIAGE_FEATURE_VERSION,
    TriageVerdict,
    evaluateTriage,
    extractTriageFeatures,
)

_BASE_TIME = datetime(2026, 11, 22, 12, 0, 0)

EXPECTED_FEATURE_KEYS = frozenset(
    {
        "humanEventDistance",
        "humanTimeDistanceSec",
        "agentStreakLength",
        "maxRepeatCount",
        "maxSimilarity",
        "messageRatePerMin",
        "userCount",
        "assistantCount",
        "meanAssistantLength",
        "maxAssistantLength",
        "questionRatio",
    }
)


def _event(role: str, content: str, offsetSeconds: float = 0.0, timestamp=None) -> dict:
    if timestamp is None:
        timestamp = (_BASE_TIME + timedelta(seconds=offsetSeconds)).isoformat()
    return {"role": role, "content": content, "timestamp": timestamp}


def _user(content: str, offsetSeconds: float = 0.0) -> dict:
    return _event("user", content, offsetSeconds)


def _assistant(content: str, offsetSeconds: float = 0.0) -> dict:
    return _event("assistant", content, offsetSeconds)


def _assistantSweep(
    count: int,
    startOffsetSeconds: float = 0.0,
    stepSeconds: float = 30.0,
    prefix: str = "assistant working message",
) -> list:
    """count 条互不相同的 assistant 消息（归一化后长度 ≥8，互不重复）。"""
    return [
        _assistant(f"{prefix} number {i} with distinct content", startOffsetSeconds + i * stepSeconds)
        for i in range(count)
    ]


class TestTriageRulesContract:
    def test_contractConstantsPinned(self):
        self._assertConstants()

    def _assertConstants(self):
        assert TRIAGE_FEATURE_VERSION == "triage-features-v1"
        assert HUMAN_WINDOW_EVENTS == 10
        assert HUMAN_WINDOW_SECONDS == 300.0
        assert AGENT_LOOP_THRESHOLD == 20
        assert REPETITION_WINDOW == 6
        assert REPETITION_MIN_DUPLICATES == 3
        assert REPETITION_MIN_LENGTH == 8
        assert SIMILARITY_THRESHOLD == 0.9
        assert MAX_WINDOW == 50

    def test_verdictIsFrozenDataclass(self):
        verdict = evaluateTriage([])
        assert isinstance(verdict, TriageVerdict)
        try:
            verdict.action = "skip"  # type: ignore[misc]
            raised = False
        except dataclasses.FrozenInstanceError:
            raised = True
        assert raised, "TriageVerdict 必须是 frozen dataclass"


class TestTriageRulesR0:
    def test_emptyWindowAllowsWithNoEvents(self):
        verdict = evaluateTriage([])
        assert verdict.action == "allow"
        assert verdict.reason == "no_events"

    def test_emptyWindowFeatureDefaults(self):
        features = extractTriageFeatures([])
        assert features["humanEventDistance"] == -1.0
        assert features["humanTimeDistanceSec"] == -1.0
        assert features["agentStreakLength"] == 0.0
        assert features["maxRepeatCount"] == 1.0
        assert features["maxSimilarity"] == 0.0
        assert features["messageRatePerMin"] == 0.0
        assert features["userCount"] == 0.0
        assert features["assistantCount"] == 0.0
        assert features["meanAssistantLength"] == 0.0
        assert features["maxAssistantLength"] == 0.0
        assert features["questionRatio"] == 0.0

    def test_lastMessageIsUserAllowsAsHumanLast(self):
        events = [_assistant("done for now", 0.0), _user("thanks, proceed", 30.0)]
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "human_last"
        assert verdict.features["humanEventDistance"] == 0.0


class TestTriageRulesR1:
    def test_humanAtEighthPositionAllowsViaTimeWindow(self):
        # 人类消息在第 8 条（index 7），其后 12 条 assistant；事件距离 12 > 10，
        # 但时间距离 120s ≤ 300s → R1 时间分支放行（§8-SB-1 回归用例）。
        events = [_assistant(f"standalone progress note {i}", i * 10.0) for i in range(7)]
        events.append(_user("please continue with the plan", 70.0))
        events.extend(_assistant(f"standalone progress note {i + 8}", (i + 8) * 10.0) for i in range(12))
        assert len(events) == 20
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "human_in_window"
        assert verdict.features["humanEventDistance"] == 12.0
        assert verdict.features["humanTimeDistanceSec"] == 120.0

    def test_humanWithinTenEventsAllowsEvenWhenTimeStale(self):
        # 事件距离 8 ≤ 10 → 放行，即使时间距离已远超 300s（R1 的 OR 另一支）。
        events = [_user("kick off now", 0.0)]
        events.extend(_assistant(f"long running step {i}", i * 400.0) for i in range(1, 9))
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "human_in_window"
        assert verdict.features["humanEventDistance"] == 8.0
        assert verdict.features["humanTimeDistanceSec"] > HUMAN_WINDOW_SECONDS


class TestTriageRulesR2:
    def test_twentyFiveAssistantOnlyMessagesSkip(self):
        events = _assistantSweep(25)
        verdict = evaluateTriage(events)
        assert verdict.action == "skip"
        assert verdict.reason == "agent_loop_no_human"
        assert verdict.features["agentStreakLength"] == 25.0
        assert verdict.features["humanEventDistance"] == -1.0

    def test_nineteenSoloAssistantStillAllows(self):
        events = _assistantSweep(19)
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "default_allow"
        assert verdict.features["agentStreakLength"] == 19.0

    def test_twentySoloAssistantSkips(self):
        events = _assistantSweep(20)
        verdict = evaluateTriage(events)
        assert verdict.action == "skip"
        assert verdict.reason == "agent_loop_no_human"
        assert verdict.features["agentStreakLength"] == 20.0


class TestTriageRulesR3:
    @staticmethod
    def _staleUserThen(assistantEvents: list) -> list:
        events = [_user("please carry on without me", 0.0)]
        events.extend(assistantEvents)
        return events

    def test_threeDuplicateLongMessagesSkip(self):
        repeated = "please review the deployment checklist again now"
        assistantEvents = _assistantSweep(8, startOffsetSeconds=40.0, stepSeconds=40.0, prefix="distinct progress note")
        assistantEvents.append(_assistant(repeated, 360.0))
        assistantEvents.append(_assistant("deploy rollback plan is ready for inspection", 400.0))
        assistantEvents.append(_assistant(repeated, 440.0))
        # 大写 + 多余空白：归一化后与 repeated 同文，证明 casefold/压缩空白生效
        assistantEvents.append(_assistant(repeated.upper() + "  ", 480.0))
        events = self._staleUserThen(assistantEvents)
        verdict = evaluateTriage(events)
        assert verdict.action == "skip"
        assert verdict.reason == "verbatim_loop"
        assert verdict.features["maxRepeatCount"] == 3.0

    def test_shortRepeatedPhrasesDoNotLoop(self):
        # 3 条"好的"（归一化长度 2 < 8）不参与复读计数 → 放行
        assistantEvents = _assistantSweep(10, startOffsetSeconds=40.0, stepSeconds=40.0, prefix="distinct progress note")
        assistantEvents.append(_assistant("好的", 440.0))
        assistantEvents.append(_assistant("好的", 480.0))
        assistantEvents.append(_assistant("好的", 520.0))
        events = self._staleUserThen(assistantEvents)
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "default_allow"
        assert verdict.features["maxRepeatCount"] == 1.0

    def test_currentInputNearlyIdenticalToRecentAssistantSkips(self):
        recent = "the quick brown fox jumps over the lazy dog near the riverbank today"
        assistantEvents = _assistantSweep(11, startOffsetSeconds=40.0, stepSeconds=40.0, prefix="distinct progress note")
        assistantEvents.append(_assistant(recent, 480.0))
        events = self._staleUserThen(assistantEvents)
        currentInput = "The quick brown fox jumps over the lazy dog near the riverbank tonight"
        verdict = evaluateTriage(events, currentInput)
        assert verdict.action == "skip"
        assert verdict.reason == "verbatim_loop"
        assert verdict.features["maxSimilarity"] >= SIMILARITY_THRESHOLD


class TestTriageRulesFeatures:
    @staticmethod
    def _mixedWindow() -> list:
        return [
            _user("你好，请帮我看看这个文件", 0.0),
            _assistant("Hello World, this is a fine reply", 10.0),
            _user("在吗？", 20.0),
            _assistant("yes no maybe so", 30.0),
            _assistant("Hello World, this is a fine reply", 40.0),
        ]

    def test_featureKeysCompleteAndDeterministic(self):
        events = self._mixedWindow()
        first = extractTriageFeatures(events, "hello world")
        second = extractTriageFeatures(events, "hello world")
        assert set(first) == set(EXPECTED_FEATURE_KEYS)
        assert first == second
        assert evaluateTriage(events, "hello world") == evaluateTriage(events, "hello world")
        for value in first.values():
            assert isinstance(value, float)

    def test_featureSemanticsOnMixedWindow(self):
        features = extractTriageFeatures(self._mixedWindow(), "")
        assert features["humanEventDistance"] == 2.0
        assert features["humanTimeDistanceSec"] == 20.0
        assert features["agentStreakLength"] == 2.0
        assert features["userCount"] == 2.0
        assert features["assistantCount"] == 3.0
        assert features["meanAssistantLength"] == 27.0  # (33+15+33)/3
        assert features["maxAssistantLength"] == 33.0
        assert features["maxRepeatCount"] == 2.0
        assert features["maxSimilarity"] == 0.0  # currentInput 为空
        assert features["messageRatePerMin"] == 5.0  # 跨度 40s<1min → 分母取 1.0
        assert features["questionRatio"] == 0.2  # "在吗？" 1/5


class TestTriageRulesTimestampRobustness:
    def test_unparseableTimestampsDegradeToEventDistance(self):
        events = [_event("user", "start now", timestamp="not-a-timestamp")]
        for i in range(5):
            events.append(_event("assistant", f"working on step {i}", timestamp="???"))
        features = extractTriageFeatures(events)
        assert features["humanEventDistance"] == 5.0
        assert features["humanTimeDistanceSec"] == -1.0
        assert features["messageRatePerMin"] == 0.0
        verdict = evaluateTriage(events)
        assert verdict.action == "allow"
        assert verdict.reason == "human_in_window"

    def test_agentLoopDetectedWithoutUsableTimestamps(self):
        events = [_event("assistant", f"unattended loop message {i}", timestamp="bad") for i in range(20)]
        verdict = evaluateTriage(events)
        assert verdict.action == "skip"
        assert verdict.reason == "agent_loop_no_human"
        assert verdict.features["humanTimeDistanceSec"] == -1.0
        assert verdict.features["agentStreakLength"] == 20.0


class TestTriageRulesWindowCap:
    def test_windowCappedAtFiftyEvents(self):
        # 51 条：user 在 index 0、其后 50 条 assistant，时间步长 6s。
        # 不封顶时 user 时间距离恰 300s ≤ 300 会走 R1 放行；
        # 封顶后 user 被挤出窗口 → 无人类 → R2 独走环拦截。
        events = [_user("early human message", 0.0)]
        events.extend(_assistant(f"capped window loop message {i}", (i + 1) * 6.0) for i in range(50))
        assert len(events) == 51
        features = extractTriageFeatures(events)
        assert features["humanEventDistance"] == -1.0
        assert features["agentStreakLength"] == 50.0
        verdict = evaluateTriage(events)
        assert verdict.action == "skip"
        assert verdict.reason == "agent_loop_no_human"
