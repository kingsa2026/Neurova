"""降频巡检的派发层回归（工单 008 交付项 3/4）。

红绿说明：
- 修前必红的是"永久自停"本身 —— 那条已由
  `tests/unit/evolution/rsi/test_rsi_loop_baseline.py::test_convergence_must_not_permanently_stop_evolution`
  在探针层跑过红→绿（实测第 20 轮 `should_continue()` 永久 False）。
- 本文件锁的是派发层的两条新契约：backoff **只降频不终止**，
  以及 SKIPPED 措辞必须说得出"哪个判据、依据什么证据"（裸 `cadence="backoff"` 字符串不够）。

替身故意**不实现** `should_continue()`：派发层若还去读那个二态开关，
这里会以 AttributeError 直接暴露，而不是被 MagicMock 的默认值悄悄放过。
"""

import asyncio
from types import SimpleNamespace

import pytest

from neurova.post_chat_pipeline import PostChatPipeline, StepStatus


class _Cadence:
    """鸭子类型的节奏读数：与 `RSIOrchestrator.iteration_cadence()` 同形。"""

    def __init__(self, mode, basis, evidence):
        self.mode = mode
        self.basis = basis
        self.evidence = evidence


class _BackoffRSI:
    def __init__(self, cadence):
        self._cadence = cadence
        self.runs = 0

    def iteration_cadence(self):
        return self._cadence

    def run_iteration(self):
        self.runs += 1
        return {"convergence": {"status": self._cadence.basis}, "applied_count": 0,
                "gain": 0.0, "phase_advanced": False, "eval": {"before": None, "after": None}}


def _make_pipe(rsi) -> PostChatPipeline:
    pipe = PostChatPipeline.__new__(PostChatPipeline)
    pipe._agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="a-cadence"), session_id="s-cadence")
    pipe._get_dependency = lambda name: rsi if name == "rsi_orchestrator" else None
    return pipe


@pytest.fixture(autouse=True)
def _isolated_turn_state():
    """轮次计数是进程级会话表，用例之间必须复位，否则 60 轮窗口被前序用例污染。"""
    from neurova.core.turn_context import clear_turn_state, set_turn_identity

    clear_turn_state()
    set_turn_identity("hi", "s-cadence")
    yield
    clear_turn_state()


@pytest.fixture(autouse=True)
def _isolated_step_results_ctx():
    token = PostChatPipeline._step_results_ctx.set([])
    yield
    PostChatPipeline._step_results_ctx.reset(token)


@pytest.fixture(autouse=True)
def _no_skill_improver(monkeypatch):
    """隔离步骤前置的技能改进扫描（与本契约无关）。"""
    improver = SimpleNamespace(
        propose_pending_improvements=lambda: [],
        apply_improvement=lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver", lambda: improver
    )


def _run_turns(pipe, turns):
    from neurova.core.turn_context import increment_turn_count

    outcomes = []
    for _ in range(turns):
        increment_turn_count()
        outcomes.append(asyncio.run(pipe._step_rsi_iteration()))
    return outcomes


def test_backoff_still_runs_on_the_patrol_window():
    """降频不是终止：60 轮里必须按窗口被重新量过，且第 60 轮仍在跑。"""
    from neurova.post_chat_pipeline import _RSI_BACKOFF_EVERY_TURNS

    rsi = _BackoffRSI(_Cadence("backoff", "measurement_blind", "窗口 20 轮内有效测量 0 轮"))
    pipe = _make_pipe(rsi)

    outcomes = _run_turns(pipe, 60)

    assert rsi.runs == 60 // _RSI_BACKOFF_EVERY_TURNS, (
        f"backoff 下 60 轮跑了 {rsi.runs} 次：既不是每轮全跑，也不是每 "
        f"{_RSI_BACKOFF_EVERY_TURNS} 轮巡检一次")
    assert outcomes[-1] is not None, "第 60 轮必须在跑"


def test_skipped_message_names_basis_and_evidence():
    """SKIPPED 必须说得出"拦在哪个判据、依据什么证据"，不得只报一个模糊状态。"""
    rsi = _BackoffRSI(_Cadence("backoff", "measurement_blind", "窗口 20 轮内有效测量 0 轮"))
    pipe = _make_pipe(rsi)

    _run_turns(pipe, 1)

    skipped = [r for r in pipe._step_results if r.status == StepStatus.SKIPPED]
    assert skipped, "不在巡检窗口时应记 SKIPPED"
    message = skipped[-1].message
    assert "measurement_blind" in message, f"未写明判据：{message}"
    assert "有效测量 0" in message, f"未写明证据：{message}"
    assert skipped[-1].data["basis"] == "measurement_blind"


def test_full_cadence_runs_every_turn_and_says_nothing_about_backoff():
    """反向一例：run 档必须每轮都跑 —— 降频逻辑不得把正常路径一起拖慢。"""
    rsi = _BackoffRSI(_Cadence("run", "converging", "窗口 20 轮内有效测量 12 轮"))
    pipe = _make_pipe(rsi)

    _run_turns(pipe, 5)

    assert rsi.runs == 5
    assert not [r for r in pipe._step_results if r.status == StepStatus.SKIPPED]
