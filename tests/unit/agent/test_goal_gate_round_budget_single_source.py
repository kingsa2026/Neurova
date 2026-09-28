# -*- coding: utf-8 -*-
"""GoalGate 轮次预算的单源收口（Issue #310 后续片）——「上限是被声明的契约」。

根因（切片 B/D/C 三次独立登记的同一形态，本片收口）：

GoalGate 的轮次预算 `max_rounds` 默认值是 `gates.py:172` 的**类字面量 15**，
`_buildGateRunner` 在默认装配路径上把它无条件塞进门控集合：

    GoalGate(maxContinuations=limits["goal_max_continuations"])   # 不传 max_rounds

于是这个 15 轮上限**不受任何配置键管辖**：`max_loop_rounds` 配到 200 也无效，
因为 GoalGate（priority=15）先于 IterationGate（priority=10）……不，是后于——
但两条路径上 GoalGate 的 `check()` 先于工具轮累加处的守卫开火。实测：

    max_loop_rounds=  20  装配={'iteration': 20, 'goal': 15}  首个终止=(15, 'goal')
    max_loop_rounds= 200  装配={'iteration': 200, 'goal': 15}  首个终止=(15, 'goal')

**同一个 15 在两档配置下都先开火**——工具轮预算配多大都不管用。这与切片 D 的
「深度是广度的副作用」同形：**上限是字面量的副作用，不是被声明的契约**。

判据（每条都要求「改前实测不成立、改后成立」）：
1. 静态：`_buildGateRunner` 默认装配路径上，GoalGate 的轮次预算**来自配置单源**
   （不是字面量），且 `set_goal_gate` 的缺省参数不再自带第二份字面量 15；
2. 静态：配置单源里有该键，且合法域夹紧存在；
3. 活体：真 `OpenAILoop` + 真门控装配，`max_loop_rounds` 从 20 改到 200 时，
   GoalGate 生效轮次预算**随之改变**（这是「被配置管辖」的直接读数）；
4. 活体（反面）：默认装配下普通对话（无目标声明）跑到工具轮上限，
   不得被 GoalGate 以其轮次预算为理由终止——`resolveTurnGoal` 为 None 时
   出口求值本就不触发，且工具轮分支不该替 IterationGate 先开火；
5. 活体：`goal_round_budget` 与其消费点跨文件（`consumed`）。

替身只放在模型边界；门控装配、配置读取、阈值比较全部走生产代码。
"""

from __future__ import annotations

import ast
import io
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = PROJECT_ROOT / "neurova"
OPENAI_LOOP = PRODUCTION / "agent" / "loops" / "openai_loop.py"
GATES = PRODUCTION / "agent" / "gates.py"
LIMITS = PRODUCTION / "security" / "agent_limits_settings.py"
LEDGER = PROJECT_ROOT / "scripts" / "ci" / "toolLoopDeadlines.txt"


def _text(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _gateBudgetInDefaultAssembly() -> int:
    """默认装配路径上 GoalGate 实际拿到的轮次预算（活体读数，非静态猜测）。"""
    from neurova.agent.loops.openai_loop import OpenAILoop

    agent = MagicMock()
    agent.config.name = "probe-agent"
    agent.config.agent_id = "probe-agent-id"
    agent.llm_client = MagicMock()
    loop = OpenAILoop(agent)
    for gate in loop._buildGateRunner().gates:
        if getattr(gate, "name", "") == "goal":
            return int(getattr(gate, "max_rounds", -1))
    raise AssertionError("默认装配里没有 goal 门控——本片的前提不成立")


class TestRoundBudgetIsDeclaredNotLiteral:
    """上限必须来自配置单源，不得是装配路径上的字面量。"""

    def test_default_assembly_budget_comes_from_config_key(self):
        """活体：默认装配的 GoalGate 轮次预算 == 配置单源的生效值。

        改前：装配恒得字面量 15，与配置键无关 ⇒ 本判据红。
        """
        from neurova.security.agent_limits_settings import get_effective_limits

        effective = get_effective_limits()
        assert "goal_round_budget" in effective, (
            "配置单源缺 `goal_round_budget`：GoalGate 的轮次预算没有可声明的键，"
            "只能回落到 gates.py 的类字面量——这正是本片要消灭的形态。"
        )
        assert _gateBudgetInDefaultAssembly() == int(effective["goal_round_budget"]), (
            "默认装配的 GoalGate 轮次预算与配置单源不一致：装配路径仍在用字面量。"
        )

    def test_config_key_follows_max_loop_rounds_when_unset(self):
        """未显式设置时，goal 轮次预算**跟随**工具轮预算——而不是那个 15。

        改前：无论 max_loop_rounds 怎么配，装配恒得 15 ⇒ 本判据红。
        """
        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        try:
            als.DEFAULTS["max_loop_rounds"] = 200
            als.DEFAULTS["goal_round_budget"] = None
            effective = als.get_effective_limits()
            assert effective["goal_round_budget"] == 200, (
                "未显式设置 goal_round_budget 时应跟随 max_loop_rounds（单源），"
                f"实测 {effective['goal_round_budget']}"
            )
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

    def test_budget_scales_with_max_loop_rounds_in_live_assembly(self):
        """活体：max_loop_rounds 由 20 改到 200，门控生效预算必须跟着变。

        改前两档都读出 15 ——「配多大都不管用」的直接读数 ⇒ 本判据红。
        """
        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        seen = {}
        try:
            for n in (20, 200):
                als.DEFAULTS["max_loop_rounds"] = n
                als.DEFAULTS["goal_round_budget"] = None
                seen[n] = _gateBudgetInDefaultAssembly()
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

        assert seen[20] != seen[200], (
            "门控轮次预算不随 max_loop_rounds 变化 —— 上限不受任何配置键管辖："
            f"{seen}"
        )
        assert seen[200] == 200, f"配到 200 时门控预算应为 200，实测 {seen[200]}"

    def test_no_literal_default_in_assembly_or_setter(self):
        """静态：装配路径与 setter 的缺省参数都不得自带第二份字面量。

        `_buildGoalGate` 的 `spec.get("max_rounds", 15)` 与
        `set_goal_gate(..., max_rounds: int = 15)` 是同一份 15 的两处落点。
        """
        src = _text(OPENAI_LOOP)
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                "_buildGoalGate",
                "set_goal_gate",
            ):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and sub.value == 15:
                        offenders.append(f"{node.name}:{sub.lineno} 仍有字面量 15")
        assert not offenders, (
            "装配/setter 路径仍自带字面量轮次预算（第二份定义）：\n  "
            + "\n  ".join(offenders)
        )


class TestGoalGateDoesNotPreemptToolRoundBudget:
    """GoalGate 的轮次预算不得替 IterationGate 先开火。"""

    def test_goal_gate_rounds_branch_requires_goal(self):
        """活体：无目标声明时，GoalGate 的轮次预算分支不得终止工具轮。"""
        from neurova.agent.gates import StopAction

        gate = _goalGateFromDefaultAssembly()
        # 无 goal、无 completion_check：与普通对话的工具轮 ctx 同形
        decision = gate.check({"tool_rounds": 99999, "goal": {}})
        assert decision.action == StopAction.BYPASS, (
            "无目标声明时 GoalGate 仍以轮次预算终止（替 IterationGate 先开火）："
            f"{decision.reason!r}"
        )

    def test_long_tool_chain_runs_to_configured_budget(self):
        """活体：普通对话跑长工具链，首个终止必须是 IterationGate 的配置值。"""
        from neurova.agent.loops.openai_loop import OpenAILoop

        agent = MagicMock()
        agent.config.name = "probe-agent"
        agent.config.agent_id = "probe-agent-id"
        agent.llm_client = MagicMock()
        loop = OpenAILoop(agent)
        state = loop._startTurnState([{"role": "user", "content": "probe"}])
        state.maxToolRounds = 30

        for r in range(1, 26):
            state.toolRounds = r
            decision = state.gateRunner.on_round_end(
                state.gateContext(toolSignatures=f"tool{r}", tool_rounds=r)
            )
            if decision.action.value != "bypass":
                assert decision.gate_name == "iteration", (
                    f"第 {r} 轮被 {decision.gate_name} 以 {decision.reason!r} 终止 —— "
                    "GoalGate 的轮次预算先于 IterationGate 开火，工具轮预算形同虚设。"
                )
                return
        pytest.fail("25 轮内没有被终止——测试自身前提（IterationGate=20）不成立")


class TestLedgerAndSingleSourceConsistency:
    def test_ledger_registers_the_new_key(self):
        text = _text(LEDGER)
        assert re.search(r"^goal_round_budget\s*\|", text, re.M), (
            "台账缺 `goal_round_budget` 行——新增阈值单源必须登记（不留只写不读）。"
        )

    def test_limits_module_declares_key_and_clamps(self):
        src = _text(LIMITS)
        assert '"goal_round_budget"' in src, "配置单源未声明 goal_round_budget"
        assert "MIN_GOAL_ROUND_BUDGET" in src and "MAX_GOAL_ROUND_BUDGET" in src, (
            "配置单源缺合法域夹紧"
        )


def _goalGateFromDefaultAssembly():
    from neurova.agent.loops.openai_loop import OpenAILoop
    from unittest.mock import MagicMock as _MM

    agent = _MM()
    agent.config.name = "probe-agent"
    agent.config.agent_id = "probe-agent-id"
    agent.llm_client = _MM()
    loop = OpenAILoop(agent)
    for gate in loop._buildGateRunner().gates:
        if getattr(gate, "name", "") == "goal":
            return gate
    raise AssertionError("默认装配里没有 goal 门控")
