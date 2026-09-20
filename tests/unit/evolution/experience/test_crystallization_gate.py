"""结晶闸必须听参数事实源（工单 004）。

审计事实：真正决定经验能否入库的是 `pattern_crystallizer.py:210/230` 的两个字面量
（`>= 3`、`< 0.6`），而 RSI 可调的 `crystallize_min_observations` /
`crystallize_min_success_rate` 挂在 `ExperienceFeedback` 上，只被 `get_feedback()`
的报表消费（`:353-354`）⇒ 调参改的是报表，不是闸。与 RSI 工单 006 的幻影守卫同型。
"""

import io
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CRYSTALLIZER_SRC = (PROJECT_ROOT / "neurova" / "cognitive_layers"
                    / "memory_layer" / "pattern_crystallizer.py")


def _observe(cryst, outcomes):
    for success in outcomes:
        cryst.observe(tool_name="pdf_export", context="导出季度报表", success=success)


def _candidate_blocked(cryst, engine) -> bool:
    """门槛是否拦住了这条模式。

    工单 005 之后"没入库"有两个原因（被门槛拦住 / 入库前还要过 LLM 裁决），
    所以判据只能看**候选有没有越过统计预筛进入待裁决队列** —— 那才是门槛的输出。
    """
    return bool(cryst.list_pending()) or bool(engine.stored)


def test_threshold_change_on_the_registry_moves_the_gate(crystallizer_with_registry_bridge):
    """把最小观察数调到 5 ⇒ 3 次观察不得结晶（004 前必红：字面量 3 说了算）。"""
    feedback, cryst, engine = crystallizer_with_registry_bridge

    feedback.crystallize_min_observations = 5
    _observe(cryst, [True, True, True])

    assert not _candidate_blocked(cryst, engine), (
        "调登记表参数改不动入库闸：读的是结晶器里的字面量")


def test_success_rate_threshold_is_respected(crystallizer_with_registry_bridge):
    """把成功率门槛调到 0.9 ⇒ 0.667 的模式不入库（004 前必红：读的是字面量 0.6）。"""
    feedback, cryst, engine = crystallizer_with_registry_bridge

    feedback.crystallize_min_success_rate = 0.9
    _observe(cryst, [True, True, False])

    assert not _candidate_blocked(cryst, engine), "成功率门槛同样绕过登记表"


def test_default_thresholds_unchanged(crystallizer_with_registry_bridge, approving_judge):
    """反向锁：不得靠"把门槛调到不可能达到"来交差 —— 默认值仍是 3 次 / 0.6。"""
    import asyncio

    _feedback, cryst, engine = crystallizer_with_registry_bridge

    _observe(cryst, [True, True, False])
    assert _candidate_blocked(cryst, engine), "默认门槛被改动，上面两条断言就失去意义"

    cryst.set_llm_judge(approving_judge)
    asyncio.run(cryst.review_pending_with_llm(llm_client=approving_judge))
    assert len(engine.stored) == 1, "通过门槛与裁决的模式应最终入库"


def test_no_literal_gate_remains_in_the_crystallizer():
    """源码级守卫：结晶器里不得再留有字面量门槛（防止又长出第二处真相）。"""
    source = io.open(CRYSTALLIZER_SRC, encoding="utf-8").read()
    body = source.split("def _try_crystallize", 1)[1].split("\n    def ", 1)[0]

    offenders = re.findall(r">=\s*3\b|<\s*0\.6\b", body)
    assert not offenders, f"结晶路径仍写字面量门槛: {offenders}"


def test_placeholder_mirror_agrees_with_the_setpoint():
    """值冲突收口：`agent_core.py:390` 曾写 0.7，而 setpoint 是 0.6。

    占位替身不供参数面（工单 018），但镜像值不一致会被读成"另有真相"。
    """
    from neurova.agent_core import _NullSystem
    from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS

    setpoint = SYSTEM_SETPOINTS["experience"]["crystallize_min_success_rate"]

    assert _NullSystem.crystallize_min_success_rate == setpoint, (
        f"占位镜像 0.7 与 setpoint {setpoint} 不一致")
    assert _NullSystem.crystallize_min_observations == 3
