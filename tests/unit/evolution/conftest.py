"""RSI 闭环探针基座（工单 001）。

设计约束 —— 后续所有 RSI 测试必须遵守：

1. **禁止私赋部署阶段**。不得写 `orch.deployment_controller._current_phase = N`。
   阶段只能经治理设置文件（`NEUROVA_GOVERNANCE_SETTINGS`）进入，
   即 `RSIOrchestrator.__init__` → `create_deployment_controller_with_settings`
   （`neurova/evolution/rsi/deployment_controller.py:156`）这条生产同构路径。
   原因：私赋会绕过正待修复的晋升判据，把缺陷洗成绿色（见工单 001「为什么它是第一张」）。
2. **禁止 MagicMock 冒充闭环系统**。四系统用真实子系统或本文件内的 `ProbeSystem`，
   原因：`tests/unit/api/test_governance_settings.py:59` 用 MagicMock 喂回滚历史，
   于是"回滚历史从不被写入"这一根因在测试里不可见。
3. **期望值来自独立真相源**（审计实测数据），不得由被测代码反算。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS

# ── 独立真相源：审计实测的生产参数值 ──────────────────────────────
# tool_memory 四参数的生产实值。前三项与 SYSTEM_SETPOINTS 相等（起点即目标 → 零梯度）；
# muscle_memory_threshold 生产实传 0.85（neurova/agent_core.py:234 → :609），
# 而 setpoint 为 0.8 —— 这是当前 RSI 唯一真实存在的梯度。
PRODUCED_TOOL_MEMORY_PARAMS: Dict[str, Any] = {
    "success_bonus": 0.1,
    "failure_penalty": 0.05,
    "decay_rate": 0.01,
    "muscle_memory_threshold": 0.85,
}

# 审计实测（2026-09-19）：默认 rsi_phase=0 连跑 60 轮 → phase 停在 1、applied 累计 0。
# 棘轮自停实测轮次：convergence_analyzer 的 window_size=20，第 20 轮判 converged。
CONVERGENCE_WINDOW_SIZE = 20


class ProbeSystem:
    """闭环系统探针桩：暴露可优化参数 + 可控反馈。

    与旧 `MockSystem` 的差别只有一个意图：**不隐藏任何键**。
    本桩未提供的参数会以 `None` 被 `get_optimizable_parameters` 读到，
    从而在评测集侧暴露为"回退 setpoint"（工单 007 的 measurement_blind 靶），
    而不是像旧桩那样悄悄参与满分计算。
    """

    def __init__(self, name: str, feedback: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, Any]] = None):
        self.probe_name = name
        self._feedback = dict(feedback or {})
        for key, value in (params or {}).items():
            setattr(self, key, value)

    def get_feedback(self) -> Dict[str, Any]:
        return dict(self._feedback)


class RsiLoopProbe:
    """RSI 闭环探针：持有编排器与四系统，提供定次迭代。"""

    def __init__(self, orchestrator: RSIOrchestrator, systems: Dict[str, Any]):
        self.orchestrator = orchestrator
        self.systems = systems
        self.results: List[Dict[str, Any]] = []

    @property
    def phase(self) -> int:
        return self.orchestrator.deployment_controller.get_current_phase()

    @property
    def applied_total(self) -> int:
        return sum(int(r.get("applied_count") or 0) for r in self.results)

    @property
    def rollback_history_size(self) -> int:
        return len(self.orchestrator.rollback_manager.get_rollback_history())

    @property
    def gains(self) -> List[float]:
        return [float(r.get("gain") or 0.0) for r in self.results]

    @property
    def convergence_status(self) -> str:
        return str(self.orchestrator.convergence_analyzer.analyze_convergence()["status"])

    @property
    def continued_at_end(self) -> bool:
        """本轮之后 post_chat 是否还会派发 RSI 迭代（post_chat_pipeline.py:2729 的判据）。"""
        return bool(self.orchestrator.should_continue())

    def run(self, iterations: int) -> "RsiLoopProbe":
        for _ in range(iterations):
            self.results.append(self.orchestrator.run_iteration())
        return self

    def run_until_arrested(self, max_iterations: int, stop_after: int = CONVERGENCE_WINDOW_SIZE) -> int:
        """迭代到 `should_continue()` 首次为 False，返回该轮序号；未自停则返回 -1。

        `stop_after` 用于避免无意义的长跑：收敛窗口本身只有 20 轮，
        超过它仍未自停即可判定"未永久自停"。
        """
        for index in range(max_iterations):
            self.results.append(self.orchestrator.run_iteration())
            if not self.orchestrator.should_continue() and index + 1 > stop_after:
                return index + 1
        return -1

    def live_params_of(self, system_name: str) -> Dict[str, Any]:
        """读取某系统当前被 RSI 观察到的参数值（用于断言参数真的动过）。"""
        found: Dict[str, Any] = {}
        for info in self.orchestrator.integration_manager.get_optimizable_parameters()[system_name]:
            found[info.name] = info.current_value
        return found


class MeasuredHarness:
    """评测集替身：按序吐分数，并如实自报证据状态（工单 007 的分母契约）。

    注入 `orchestrator._eval_harness` 而不是 patch `_measure_performance`：
    后者会连带跳过 `_last_eval_outcome` 的写入，于是该轮在 008 的喂数门前
    直接判为"无证据"，被测语义就与门无关了。替身必须走完真实读数路径。
    """

    def __init__(self, scores, state: str = "measured", evidenced_cases: int = 9):
        self._scores = iter(scores)
        self._state = state
        self._evidenced_cases = evidenced_cases

    def run(self, live_params: Dict[str, Any]) -> Dict[str, Any]:
        evidenced = self._state == "measured"
        return {
            # 失明时没有分数可给：评测集报 measurement_blind 时 score 必须是 None，
            # 编排器据此走 `_measure_performance` 的失明分支（不得伪造一个数）
            "score": next(self._scores) if evidenced else None,
            "state": self._state,
            "evidenced_cases": self._evidenced_cases if evidenced else 0,
            "blind_cases": 0 if evidenced else 9,
            "cases": [],
        }


@pytest.fixture
def measured_eval_harness():
    """构造自报 `measured` 的评测集替身：``measured_eval_harness([0.5, 0.8])``。"""
    return lambda scores, **kw: MeasuredHarness(scores, **kw)


@pytest.fixture
def blind_eval_harness():
    """构造自报 `measurement_blind` 的评测集替身（分数为 None = 量不出来）。"""
    return lambda: MeasuredHarness([], state="measurement_blind", evidenced_cases=0)


def _write_governance_settings(tmp_path, monkeypatch, settings: Dict[str, Any]) -> None:
    """把治理设置写进临时文件并经 env 生效（生产同构路径，替代私赋 phase）。"""
    path = tmp_path / "governance_settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


@pytest.fixture
def rsi_probe_factory(tmp_path, monkeypatch):
    """构造探针。

    用法：``probe = rsi_probe_factory(rsi_phase=0)``。
    阶段经治理设置进入，因此 005 的"晋升回写治理设置"一落地，
    本 fixture 无需改动即可覆盖重启语义。
    """

    def _factory(rsi_phase: int = 0, *, systems: Optional[Dict[str, Any]] = None,
                 tool_memory_params: Optional[Dict[str, Any]] = None) -> RsiLoopProbe:
        _write_governance_settings(
            tmp_path, monkeypatch, {"rsi_phase": rsi_phase,
                                    "conversation_rules_enabled": False}
        )
        built = systems or _default_systems(tool_memory_params)
        orchestrator = RSIOrchestrator(
            sleep_system=built["sleep"],
            emotion_system=built["emotion"],
            experience_system=built["experience"],
            tool_memory_system=built["tool_memory"],
        )
        return RsiLoopProbe(orchestrator, built)

    return _factory


def _default_systems(tool_memory_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """四系统默认装配：能上真实子系统就上真实的，剩下的用 ProbeSystem。

    - ``sleep`` / ``experience``：真实 ``SleepConsolidation`` / ``ExperienceFeedback``。
      实测其默认值即 setpoint（0.1/0.7 与 3/0.6/2）→ 这两族零候选，
      用于驱动"无证据"分支。
    - ``emotion``：桩。真实 ``EmotionModule`` 需 db_path 且其保护参数经
      ``attach_temperature_engine`` 桥接到 TemperatureEngine（agent_core.py:1534），
      直构真实类会引入与闭环判据无关的 IO。
    - ``tool_memory``：桩 + 生产实值（含唯一的真实梯度 0.85 vs setpoint 0.8）。
    """
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    from neurova.evolution.experience_feedback import ExperienceFeedback

    return {
        "sleep": SleepConsolidation(),
        "emotion": ProbeSystem(
            "emotion",
            feedback={"success_rate": 0.5},
            params={
                "emotional_protection_threshold": SYSTEM_SETPOINTS["emotion"][
                    "emotional_protection_threshold"
                ],
                "emotional_protection_factor": SYSTEM_SETPOINTS["emotion"][
                    "emotional_protection_factor"
                ],
            },
        ),
        "experience": ExperienceFeedback(),
        "tool_memory": ProbeSystem(
            "tool_memory",
            feedback={"total_usages": 50, "success_rate": 0.5},
            params=tool_memory_params or PRODUCED_TOOL_MEMORY_PARAMS,
        ),
    }


@pytest.fixture
def probe_tool_memory_system() -> ProbeSystem:
    """带生产实值的 tool_memory 探针桩（含唯一真实梯度 0.85 vs setpoint 0.8）。"""
    return ProbeSystem(
        "tool_memory",
        feedback={"total_usages": 50, "success_rate": 0.5},
        params=PRODUCED_TOOL_MEMORY_PARAMS,
    )


@pytest.fixture
def null_systems() -> Dict[str, Any]:
    """四系统全部由 `_NullSystem` 顶替 —— 复现 agent_core.py:1537-1540 的缺席装配。"""
    from neurova.agent_core import _NullSystem

    return {name: _NullSystem() for name in ("sleep", "emotion", "experience", "tool_memory")}


@pytest.fixture
def fake_skill():
    """技能桩：skill_id != name。

    旧桩（tests/unit/skills/test_improvement_persistence.py:47-52）令 id==name，
    掩盖了 skill_system.py:505（键=name）与 skill_contract.py:88-92（身份=skill_id）
    的双键域缺陷。工单 013/014 复用本桩。
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        skill_id="skill_ab12cd34ef56ab12cd34ef56ab12cd34",
        name="read_write_skill_alpha",
        config={"tool_sequence": ["read_file", "write_file"], "improvements": []},
    )
