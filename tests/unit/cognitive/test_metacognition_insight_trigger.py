# -*- coding: utf-8 -*-
"""元认知条数恒 0 的两处根修：反思触发的重启脆弱性＋sequence 门槛借常量。

诊断（2026-11-12 生产库实证，全链路逐环节核过）：
- 条数 = kind='thought' 条目 = 洞察镜像产物；管道本身健康（事件挂点→台账→
  五算子→镜像→读面，双 agent dry-run 零异常、读面 kind 过滤正确）。
- 恒 0 的原因一（触发链）：反思挂在 `turn_count % 10` 上，而 turn_count 是
  **进程内存计数**——重启清零。开发机一天重启数次，kai（71 条工具事件、
  web_fetch 已到 35/40）从未凑满重启后 10 轮，其事件**一次都没被编译过**；
  600s 节流阈值 `_last_reflect_at` 同样不持久。洞察编译器的天然触发信号是
  **新证据量**，不是轮次：本批加事件量通道（≥20 条未编译事件即反思，判定用
  持久化的台账最后反思时刻，重启不丢）。
- 恒 0 的原因二（算子门槛借常量）：`_op_sequence` 的 per-tool 门槛借了 drift
  的窗口常量 `_MIN_WINDOW=10`——连败阈值 5 本身内建样本量语义（5 连败在健康
  成功率下是极小概率事件），额外要求 10 条只会延迟天然告警。本批给它专属
  常量 `_SEQUENCE_MIN_EVENTS = 5`（足以容纳一次 5 连败的最小样本）。

诚实预期：修复后 kai 下轮对话即产生反思记录（历史页可见），但**条数不会立即
变非 0**——现有事件确实不构成统计异常（web_fetch 94% 成功率是健康的）。教训
会直接停用工具（avoid_tool 经调控门生效），门槛的意义就是宁可晚报不可错报；
web_fetch 再积累 5 次调用即达 drift 门槛，届时真实异常立即可见。
"""
from __future__ import annotations

import time

import pytest

from neurova.cognitive_layers.meta_cognition_layer import self_model as sm
from neurova.cognitive_layers.meta_cognition_layer.ledger import MetaLedger


@pytest.fixture()
def engine(tmp_path):
    ledger = MetaLedger(db_path=":memory:")
    eng = sm.SelfModelEngine(agent_id="audit-trigger", ledger=ledger, reflect_interval=0)
    yield eng
    try:
        ledger.close()
    except Exception:
        pass


class TestSequenceFloorDeconflated:
    """连败阈值 5 自带样本量语义：5-9 条事件里的 5 连败必须告警（原来被借来的
    10 条门槛拦住）。低于连败阈值本身的样本与不足连败的样本保持静默。"""

    def _streak_events(self, engine, tool, fails, successes_after=0):
        for _ in range(fails):
            engine.record_tool_event(tool, success=False, duration_ms=10.0)
        for _ in range(successes_after):
            engine.record_tool_event(tool, success=True, duration_ms=10.0)
        return list(reversed(engine.ledger.list_events(agent_id="audit-trigger", limit=2000)))

    def test_five_streak_in_six_events_now_fires(self, engine):
        events = self._streak_events(engine, "flaky_tool", fails=5, successes_after=1)

        lessons = engine._op_sequence(events, [])

        assert len(lessons) == 1, (
            f"6 条事件里的 5 连败没告警（门槛仍是借来的 10 条）：{lessons}")
        assert lessons[0]["subject"] == "flaky_tool"

    def test_below_streak_threshold_stays_silent(self, engine):
        events = self._streak_events(engine, "mild_tool", fails=3, successes_after=3)

        assert engine._op_sequence(events, []) == [], "4 条样本 3 连败就告警＝噪声教训"

    def test_enough_events_without_streak_stays_silent(self, engine):
        for i in range(12):
            engine.record_tool_event("steady_tool", success=(i % 2 == 0), duration_ms=10.0)
        events = list(reversed(engine.ledger.list_events(agent_id="audit-trigger", limit=2000)))

        assert engine._op_sequence(events, []) == [], "无连败也告警＝判据坏了"


class TestEventVolumeTrigger:
    """反思触发的证据量通道：未编译事件 ≥ 阈值即到点，与轮次门并联；
    判定基准是台账里最后一次反思（持久化），重启不丢。"""

    def test_all_events_counted_when_never_reflected(self, engine):
        for i in range(3):
            engine.record_tool_event(f"t{i}", success=True, duration_ms=1.0)

        assert engine.events_since_last_reflect() == 3

    def test_only_events_after_last_reflection_count(self, engine):
        for i in range(5):
            engine.record_tool_event(f"t{i}", success=True, duration_ms=1.0)
        engine.reflect(trigger="periodic_turn")
        for i in range(7):
            engine.record_tool_event(f"u{i}", success=True, duration_ms=1.0)

        assert engine.events_since_last_reflect() == 7, "已编译过的事件又计了一遍"

    def test_reflect_due_on_event_volume_even_off_turn_gate(self, engine):
        for i in range(sm._REFLECT_EVENT_THRESHOLD):
            engine.record_tool_event(f"t{i}", success=True, duration_ms=1.0)

        assert engine.reflect_due(turn_count=3) is True, (
            "轮次门未到但证据量已够，却不反思＝触发链仍绑死轮次")

    def test_below_event_volume_and_off_turn_gate_stays_due_false(self, engine):
        for i in range(sm._REFLECT_EVENT_THRESHOLD - 1):
            engine.record_tool_event(f"t{i}", success=True, duration_ms=1.0)

        assert engine.reflect_due(turn_count=3) is False

    def test_turn_gate_still_works(self, engine):
        assert engine.reflect_due(turn_count=10) is True
        assert engine.reflect_due(turn_count=0) is False, "0 轮也要反思＝空跑"

    def test_interval_throttle_still_applies(self, engine):
        engine._reflect_interval = 600  # 夹具默认 0＝节流永不生效，测不了本格
        for i in range(sm._REFLECT_EVENT_THRESHOLD):
            engine.record_tool_event(f"t{i}", success=True, duration_ms=1.0)
        engine._last_reflect_at = time.time()  # 刚反思过

        assert engine.reflect_due(turn_count=10) is False, "600s 节流被事件量通道绕过"
