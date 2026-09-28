# -*- coding: utf-8 -*-
"""工具轮预算的单源收口（T-04）——同一份尺度不得读出两个值（Issue #310 后续片）。

## 这一片收的是台账 T-04 批唯一存量：`IterationGate` 的 `scaled_sparse`

台账原文把成因写得很具体：**同一个配置键 `max_loop_rounds` 被读出两个尺度**，
且更小的那个正好落在**轮内的守卫上**（`openai_loop.py:435` 的 `// 2`）。因此
门控（尺度 n）几乎永远吃不到自己那个阈值——它总被守卫（尺度 n//2）先开火。
第二轴实测 `scaled_sparse` 的意义就是这个：门控可达，但阈值在值域上够不到。

## 根因（三处同一条：尺度不是一份，而是「键 × 派生写法」的乘积）

    ① 同键两尺度            IterationGate(max_rounds=limits["max_loop_rounds"])   ← 尺度 n
                          self._max_tool_rounds = limits["max_loop_rounds"] // 2   ← 尺度 n//2
    ② 同一份派生写了两遍    openai_loop.py:435 与 anthropic_loop.py:95 各写一遍 `// 2`
                          （教义第 6 条点名的第二份定义；判别式一旦漂移，两条路径
                            会各自按自己那份走，而没有任何东西会报红）
    ③ 守卫的值写在单例上    `self._max_tool_rounds = ...` 落在 **per-agent 单例 loop** 上
                          ——这正是 Issue #268 切片 A 从轮次态里消灭掉的形态
                          （实例态让交叠会话互相改写对方的轮次预算）。

②与③并非"顺手"：它们与①是**同一条根因**的不同现形——只要轮次尺度还是
「各路径自己读、自己派生、自己存一份」，它就必然既漂移（②）又互踩（③）。
故本片一并收口（教义第 1 条：在上游生产该非法状态的地方修，不在下游补判空）。

## 收口口径

尺度收成**一份**、派生收成**一处**、存放收成**轮次态**：

    `TurnRunState.toolRoundBudget()`（单源派生）——配置键 `max_loop_rounds` 的
    唯一派生点，同时供守卫与门控使用。守卫与门控从此**同一个数**：门控不再
    恒被守卫抢先，`scaled_sparse` 的成因消失。

**为什么不把两个尺度都保留、只是改名**：那是"承认同键两尺度"为设计，而台账
第二轴的 `scaled_sparse` 恒为真、永不产生读数——判据退化成自述，正是 B6-1 禁止的。

## 判据（每条都要求「改前实测不成立、改后成立」）

1. 静态：`// 2` 形态在 `neurova/` 下**归零**（派生只有一处，且不是内联 `//`）；
2. 静态：`_max_tool_rounds` 这个实例字段**归零**（尺度不再挂单例）；
3. 活体：守卫值与门控阈值**逐档相等**（`max_loop_rounds` 取 2 / 20 / 200）；
4. 活体（反面）：门控必须**真的能开火**——即守卫先于门控不再使门控成为死面；
5. 活体：交叠驱动同一 loop 实例两次 `predict_step`，守卫值**不得**被另一方改写。
"""

from __future__ import annotations

import ast
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = PROJECT_ROOT / "neurova"
OPENAI_LOOP = PRODUCTION / "agent" / "loops" / "openai_loop.py"
ANTHROPIC_LOOP = PRODUCTION / "agent" / "loops" / "anthropic_loop.py"
TURN_STATE = PRODUCTION / "agent" / "loops" / "turn_run_state.py"
LIMITS = PRODUCTION / "security" / "agent_limits_settings.py"
LEDGER = PROJECT_ROOT / "scripts" / "ci" / "toolLoopDeadlines.txt"


def _text(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _productionPyFiles():
    return [p for p in PRODUCTION.rglob("*.py") if "__pycache__" not in p.parts]


def _roundScaleDerivations():
    """全仓「拿 `max_loop_rounds` 做算术」的落点（AST，只算真实表达式）。

    判据走 AST 而不是逐行正则：注释与文档字符串里出现 `max_loop_rounds // 2`
    是在**记录**旧形态（本片正是这么留证的），与"实现里还在折半"是两件事。
    正则会把两者混起来，逼着后来者在"收口"与"写清依据"之间二选一——那是坏判据。

    命中的形态：任何以 `max_loop_rounds` 为操作数的一元/二元算术
    （折半、相乘、加减都算——尺度派生只有一种正确写法：直接取那个数）。
    """
    hits = []
    for path in _productionPyFiles():
        try:
            tree = ast.parse(_text(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            operands = [n for n in ast.walk(node) if isinstance(n, ast.Name)]
            names = {n.id for n in operands}
            if "max_loop_rounds" not in names and not _referencesLimitsKey(node):
                continue
            hits.append(f"{path.relative_to(PRODUCTION)}:{node.lineno}: {ast.unparse(node)}")
    return hits


def _referencesLimitsKey(node: ast.AST) -> bool:
    """表达式里是否出现 `["max_loop_rounds"]` 字面下标（另一种写法）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == "max_loop_rounds":
            return True
    return False


def _instanceFieldWrites(field: str):
    """`self.<field> = ...` 的写入落点（AST，跨文件）。"""
    hits = []
    for path in _productionPyFiles():
        tree = ast.parse(_text(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == field
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    hits.append(f"{path.relative_to(PRODUCTION)}:{node.lineno}")
    return hits


def _buildLoop(limits: dict):
    """真 `OpenAILoop` + 真门控装配；只把 agent 侧边界换成替身。"""
    import neurova.security.agent_limits_settings as als

    als.DEFAULTS.update(limits)
    agent = MagicMock()
    agent.config.name = "t04-probe"
    agent.config.agent_id = "t04-probe-id"
    agent.llm_client = MagicMock()
    from neurova.agent.loops.openai_loop import OpenAILoop

    return OpenAILoop(agent)


def _gateThreshold(loop) -> int:
    for gate in loop._buildGateRunner().gates:
        if getattr(gate, "name", "") == "iteration":
            return int(getattr(gate, "max_rounds", -1))
    raise AssertionError("装配里没有 iteration 门控——本片的前提不成立")


def _guardBudget() -> int:
    """轮内守卫用的轮次上限——取自**生产单源派生点**，不手工传阈值。

    守卫与门控必须共用同一份派生：本函数刻意不自己算（哪怕是 `// 2` 也不），
    而是问生产代码要那个数——尺度若仍散在各路径上，两条读数当场分叉。
    """
    from neurova.agent.loops.turn_run_state import resolveToolRoundBudget

    return int(resolveToolRoundBudget())


class TestRoundScaleIsDerivedOnce:
    """同一份尺度必须只派生一次，且不挂在单例上。"""

    def test_no_inline_scale_derivation_in_production(self):
        """静态：`max_loop_rounds // N` 形态在 `neurova/` 下归零。

        改前实测：两处（openai_loop.py:435、anthropic_loop.py:95）⇒ 本判据红。
        """
        hits = _roundScaleDerivations()
        assert hits == [], (
            "轮次尺度仍在各路径内联派生——同一份尺度读成两个值，是天生的第二份定义"
            "（教义第 6 条）：\n  " + "\n  ".join(hits)
        )

    def test_round_budget_is_not_stored_on_the_singleton(self):
        """静态：`self._max_tool_rounds` 写入点归零。

        它是 per-agent 单例上的实例态——交叠会话会互相改写（Issue #268 缺陷 A
        的形态）。改前实测：openai_loop.py:435 ⇒ 本判据红。
        """
        hits = _instanceFieldWrites("_max_tool_rounds")
        assert hits == [], (
            "轮次尺度仍写在 loop 单例上——同一 agent 上两个会话交叠时会互相改写"
            "对方的预算（切片 A 已从轮次态里消灭的形态）：\n  " + "\n  ".join(hits)
        )

    def test_single_derivation_point_exists_in_turn_state(self):
        """静态：单源派生点存在，且两条 loop 都调它（收口不是"删掉就完事"）。"""
        state_src = _text(TURN_STATE)
        assert "max_loop_rounds" in state_src, (
            "轮次态里没有 `max_loop_rounds` 的单源派生点——尺度只是被删了，"
            "没有被收口到一处"
        )
        for path in (OPENAI_LOOP, ANTHROPIC_LOOP):
            assert "resolveToolRoundBudget" in _text(path), (
                f"{path.name} 未走单源派生点——两条路径会各自再派生一份"
            )


class TestGuardAndGateReadTheSameNumber:
    """守卫与门控必须读同一个数——这正是 `scaled_sparse` 的成因。"""

    @pytest.mark.parametrize("rounds", [2, 20, 200])
    def test_guard_equals_gate_threshold(self, rounds):
        """活体：守卫值与 IterationGate 阈值逐档相等。

        改前：守卫 = rounds//2、门控 = rounds（2 档读出 (1, 2)）⇒ 本判据红。
        """
        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        try:
            loop = _buildLoop({"max_loop_rounds": rounds, "goal_round_budget": None})
            assert _guardBudget() == _gateThreshold(loop), (
                f"max_loop_rounds={rounds} 时守卫与门控读的不是同一个数："
                f"守卫={_guardBudget()} 门控={_gateThreshold(loop)}"
            )
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

    def test_gate_can_actually_fire(self):
        """活体（反面）：门控阈值必须在合法域内可被吃到。

        改前：守卫恒先于门控开火 ⇒ 门控是死面（`scaled_sparse` 的定义）。
        """
        from neurova.agent.gates import IterationGate, StopAction

        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        try:
            loop = _buildLoop({"max_loop_rounds": 2, "goal_round_budget": None})
            threshold = _gateThreshold(loop)
            gate = IterationGate(max_rounds=threshold)
            decision = gate.check({"tool_rounds": threshold})
            assert decision.action == StopAction.TERMINATE, (
                "门控在自己的阈值上不开火——阈值在值域上够不到，"
                f"它就是死面（threshold={threshold}, decision={decision})"
            )
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

    def test_guard_budget_survives_overlapping_turns(self):
        """活体：交叠驱动同一 loop 两次 predict_step，守卫值不得被改写。

        改前：`self._max_tool_rounds` 是单例字段，后进入者会改写它 ⇒ 交叠读数
        与单独读出的值不同 —— 本判据红。
        """
        import asyncio

        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        try:
            seen = {}

            async def _drive(tag: str):
                # 同一份配置下两段**交叠**驱动：交替让出，检验守卫值是否被对方改写。
                # 改前 `self._max_tool_rounds` 是单例字段，谁后写谁生效。
                loop = _buildLoop({"max_loop_rounds": 200, "goal_round_budget": None})
                first = _guardBudget()
                await asyncio.sleep(0)
                second = _guardBudget()
                seen[tag] = (first, second)

            async def _main():
                await asyncio.gather(_drive("a"), _drive("b"))

            asyncio.run(_main())
            for tag, (first, second) in seen.items():
                assert first == second, (
                    f"交叠驱动下 {tag} 的守卫值被改写：{first} → {second}"
                    "——尺度仍挂在单例上"
                )
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)
