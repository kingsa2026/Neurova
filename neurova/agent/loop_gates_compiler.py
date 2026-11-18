# -*- coding: utf-8 -*-
"""声明式停止门编译器（对照批 B1）。

把"本轮循环用哪些停止门、阈值多少"从**硬编码装配**升级为**可声明的规格**：
调用方给 JSON 形态的 specs（如 `[{"kind": "iteration", "max_rounds": 12}]`），
本模块校验后编译成既有的 `GateRunner`/`StopGate` 装配。

纪律边界：
- **门目录是单一事实源**：kind → 工厂只在此处登记；未知 kind 直接 ValueError
  （fail-closed，不静默跳过——拼错名字的声明必须当场炸出来）；
- **specs 未声明（None/空）→ 返回 None**，调用方回落既有默认装配——默认行为
  零变化；声明了就**完全按声明**（不与默认装配做并集，避免两套口径叠加）；
- GoalGate 不进目录：它绑定 goal 声明与验收回调（非纯参数门），仍走既有
  `_buildGateRunner` 的 goal 装配路径。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.agent.gates import (
    DoomLoopGate,
    GateRunner,
    IterationGate,
    StopGate,
    TokenBudgetGate,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 门目录：kind → 工厂（参数即该门构造函数的关键字参数）。
#: 新增门在这里登记一处即可被声明使用（单一事实源）。
GATE_CATALOG = {
    "iteration": IterationGate,
    "token_budget": TokenBudgetGate,
    "doom_loop": DoomLoopGate,
}

#: 各门允许的参数键（白名单——声明里多写的键是笔误，直接拒绝）。
GATE_PARAM_WHITELIST = {
    "iteration": {"max_rounds"},
    "token_budget": {"max_tokens"},
    "doom_loop": {"window_size", "similarity_threshold", "max_interrupts"},
}


def compileLoopGates(
    specs: Optional[List[Dict[str, Any]]],
    limits: Dict[str, Any],
) -> Optional[GateRunner]:
    """把声明 specs 编译成 GateRunner。

    Args:
        specs: 门声明列表，每项 `{"kind": ..., **params}`；None/空 = 未声明。
        limits: 配置单源阈值（`agent_limits_settings.DEFAULTS` 同形），
            未显式给参的门从这里取默认——与既有装配同一取数源。

    Returns:
        GateRunner（specs 非空时）；None（未声明，调用方回落默认装配）。

    Raises:
        ValueError: kind 不在目录 / 参数键越界 / 同类门重复。
    """
    if not specs:
        return None

    gates: List[StopGate] = []
    seen_kinds: set = set()
    for index, item in enumerate(specs):
        if not isinstance(item, dict):
            raise ValueError(f"loop_gates[{index}] 必须是对象：{item!r}")
        kind = str(item.get("kind") or "").strip()
        factory = GATE_CATALOG.get(kind)
        if factory is None:
            raise ValueError(
                f"loop_gates[{index}].kind 未知：{kind!r}（可用：{sorted(GATE_CATALOG)}）")
        if kind in seen_kinds:
            raise ValueError(f"loop_gates[{index}].kind 重复：{kind!r}")
        seen_kinds.add(kind)

        allowed = GATE_PARAM_WHITELIST[kind]
        params = {k: v for k, v in item.items() if k != "kind"}
        unknown = set(params) - allowed
        if unknown:
            raise ValueError(
                f"loop_gates[{index}]（{kind}）存在未知参数：{sorted(unknown)}（允许：{sorted(allowed)}）")

        # 未显式声明的参数取配置单源默认（与既有装配同一取数，不手抄数字）
        defaults = _defaultsForKind(kind, limits)
        merged = {**defaults, **params}
        gates.append(factory(**merged))
        logger.info("loop_gates[%d] 编译：%s %s", index, kind, merged)

    return GateRunner(gates)


def _defaultsForKind(kind: str, limits: Dict[str, Any]) -> Dict[str, Any]:
    """各门的配置单源默认参数（与 `_buildGateRunner` 既有取数同源）。"""
    if kind == "iteration":
        return {"max_rounds": int(limits.get("max_loop_rounds", 0)) or None}
    if kind == "token_budget":
        return {"max_tokens": int(limits.get("token_budget", 0)) or None}
    if kind == "doom_loop":
        return {
            "window_size": int(limits.get("doom_loop_window_size", 0)) or None,
            "similarity_threshold": float(limits.get("doom_loop_similarity_threshold", 1.0)),
            "max_interrupts": int(limits.get("doom_loop_max_interrupts", 0)) or None,
        }
    return {}
