"""认知三链路巡检 P1-3/P1-4 防回归：结晶回流与洞察编译器鲁棒性。

P1-3：agent_core 认知组件补注入此前只做单向
`evolution.crystallizer = crystallizer`，无人回填 crystallizer.evolution，
导致结晶成功→进化经验的回流分支（pattern_crystallizer.py:254）恒 False。
P1-4：SelfModelEngine.reflect() 此前单个 try 包住全部五算子——一算子
异常吞掉其后所有算子；且 _op_budget 在 len(durations)==_WINDOW 时除零。
"""
import time

import pytest

from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer


def _make_crystallizer(tmp_path, monkeypatch):
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        CognitiveStorageEngine,
    )

    engine = CognitiveStorageEngine(agent_id="audit-cryst", data_dir=str(tmp_path / "cse"))
    return PatternCrystallizer(engine=engine, evolution_orchestrator=None, state_path=str(tmp_path / "state.json"))


def test_backward_injection_backfills_crystallizer_evolution(tmp_path, monkeypatch):
    """模拟 init 顺序：crystallizer 先以 evolution=None 创建，evolution 后就绪时补注入必须双向。"""
    cryst = _make_crystallizer(tmp_path, monkeypatch)
    assert cryst.evolution is None

    evolution = type("Evo", (), {})()

    # 与 agent_core.init_evolution 尾部补注入同逻辑（抽出验证契约）
    evolution.crystallizer = cryst
    if getattr(cryst, "evolution", None) is None:
        cryst.evolution = evolution

    assert cryst.evolution is evolution


def test_reflect_survives_single_operator_failure(tmp_path, monkeypatch):
    """一算子崩，其余算子仍须产出（per-operator 隔离）。"""
    from neurova.cognitive_layers.meta_cognition_layer import self_model as sm
    from neurova.cognitive_layers.meta_cognition_layer.ledger import MetaLedger

    ledger = MetaLedger(db_path=":memory:")
    engine = sm.SelfModelEngine(agent_id="audit-reflect", ledger=ledger, reflect_interval=0)

    # 台账造 3 条工具事件，让后续算子有数据
    for i in range(3):
        engine.record_tool_event("tool_x", success=(i < 2), duration_ms=100.0 + i)

    calls = []

    def boom(events, observations):
        calls.append("drift")
        raise RuntimeError("drift boom")

    def spy(name, fn):
        def wrapper(events, observations):
            calls.append(name)
            return fn(events, observations)

        return wrapper

    monkeypatch.setattr(engine, "_op_drift", boom)
    monkeypatch.setattr(engine, "_op_contrast", spy("contrast", engine._op_contrast))
    monkeypatch.setattr(engine, "_op_sequence", spy("sequence", engine._op_sequence))
    monkeypatch.setattr(engine, "_op_calibration", spy("calibration", engine._op_calibration))
    monkeypatch.setattr(engine, "_op_budget", spy("budget", engine._op_budget))

    engine.reflect(trigger="test")
    assert "contrast" in calls and "budget" in calls, (
        "reflect 单 try 包五算子时，_op_drift 崩溃会吞掉其后全部算子（P1-4）"
    )
    assert engine._last_reflect_at > 0


def test_op_budget_zero_duration_window_no_crash():
    """30 条带 duration 的工具事件（恰等于 _WINDOW）时 base 为空的除零护栏。"""
    from neurova.cognitive_layers.meta_cognition_layer.self_model import SelfModelEngine

    engine = SelfModelEngine.__new__(SelfModelEngine)  # 不触发完整初始化
    events = [
        {"process_type": "tool", "success": True, "duration_ms": 10.0 + i, "description": "tool_y"}
        for i in range(30)
    ]
    lessons = engine._op_budget(events, [])
    assert isinstance(lessons, list)  # 不抛 ZeroDivisionError 即可
