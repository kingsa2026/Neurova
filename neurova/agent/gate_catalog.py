# -*- coding: utf-8 -*-
"""
GateCatalog 声明式门控配置层

NV 的 gates.py 提供全部执行面（DoomLoop/Iteration/TokenBudget/GoalGate +
GateRunner 故障隔离）。本模块补配置层：
- 可配置白名单：iteration / token_budget / doom_loop
  （goal 类由轮次目标槽 + Loop 出口求值承载，不走配置层）
- pydantic 严格参数校验（extra=forbid：未知参数 fail fast）
- describe()：输出各 gate 的参数 JSON Schema 形状（给前端配置 UI）
- compile_gates()：先全量验证再构建（原子语义：一个非法全部不建）

排他性约束预留 exclusive_group 字段（当前白名单内无互斥对）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurova.agent.gates import (
    DoomLoopGate,
    IterationGate,
    StopGate,
    TokenBudgetGate,
)
# 死循环门三键的合法域取配置单源的常量，不在本档重打数字（重打的那份一旦与单源不一致，
# 声明式编出来的门与装配点门就按两种语义判重复，两边测试各自都绿）
from neurova.security.agent_limits_settings import (
    MAX_DOOM_LOOP_INTERRUPTS,
    MAX_DOOM_LOOP_SIMILARITY,
    MAX_DOOM_LOOP_WINDOW,
    MIN_DOOM_LOOP_INTERRUPTS,
    MIN_DOOM_LOOP_SIMILARITY,
    MIN_DOOM_LOOP_WINDOW,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)


# ── 参数模型（extra=forbid：未知参数拒绝） ──


class IterationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_rounds: int = 20


class TokenBudgetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tokens: int = 100000


class DoomLoopParams(BaseModel):
    """死循环门的声明式参数。三键全部**可缺省**，缺省即由门自取配置单源的默认值。

    为什么不在这里写默认数字：这道门的三个阈值在
    `security/agent_limits_settings.DEFAULTS` 已有一份权威值，此处再抄一份就是第二份定义
    ——而它一旦与单源不一致（本档曾把 `similarity_threshold` 抄成 0.95，而单源为
    实装后的保守默认 1.0），声明式配置编出来的门与 `_buildGateRunner` 装配出来的门
    就会按两种语义判重复，两边各自测试都绿。合法域取单源的 MIN/MAX 常量。
    """

    model_config = ConfigDict(extra="forbid")
    window_size: Optional[int] = Field(
        default=None, ge=MIN_DOOM_LOOP_WINDOW, le=MAX_DOOM_LOOP_WINDOW)
    similarity_threshold: Optional[float] = Field(
        default=None, gt=MIN_DOOM_LOOP_SIMILARITY - 1e-9, le=MAX_DOOM_LOOP_SIMILARITY)
    max_interrupts: Optional[int] = Field(
        default=None, ge=MIN_DOOM_LOOP_INTERRUPTS, le=MAX_DOOM_LOOP_INTERRUPTS)


class _GateSpec:
    """单个可配置 gate 的规格（类 + 参数模型 + 构建器 + 元信息）。"""

    def __init__(
        self,
        gate_cls: Type[StopGate],
        params_model: Type[BaseModel],
        priority: int,
        cost: str = "none",
        exclusive_group: str = "",
        description: str = "",
    ):
        self.gate_cls = gate_cls
        self.params_model = params_model
        self.priority = priority
        self.cost = cost  # "none" | "model_call"
        self.exclusive_group = exclusive_group
        self.description = description

    def build(self, params: Dict[str, Any]) -> StopGate:
        validated = self.params_model(**params)
        return self.gate_cls(**validated.model_dump())

    def schema(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "cost": self.cost,
            "exclusive_group": self.exclusive_group or None,
            "description": self.description,
            "params": self.params_model.model_json_schema()["properties"],
        }


# 白名单（goal 不在列：需运行时 completion_check 回调）
_SPECS: Dict[str, _GateSpec] = {
    "iteration": _GateSpec(
        gate_cls=IterationGate,
        params_model=IterationParams,
        priority=10,
        description="工具调用轮次上限（ctx.tool_rounds 达 max_rounds 即 TERMINATE）",
    ),
    "token_budget": _GateSpec(
        gate_cls=TokenBudgetGate,
        params_model=TokenBudgetParams,
        priority=20,
        description="会话 token 预算上限",
    ),
    "doom_loop": _GateSpec(
        gate_cls=DoomLoopGate,
        params_model=DoomLoopParams,
        priority=5,
        description="死循环门控：滑动窗口签名 + 重复中断计数",
    ),
}


class GateCatalog:
    """声明式门控目录：白名单 + 参数 schema。"""

    def __init__(self, specs: Dict[str, _GateSpec] = None):
        self._specs = specs if specs is not None else _SPECS

    def describe(self) -> Dict[str, Any]:
        """各 gate 的参数 schema（前端配置 UI 直接消费）。"""
        return {name: spec.schema() for name, spec in self._specs.items()}

    def get_spec(self, gate_type: str) -> _GateSpec:
        spec = self._specs.get(gate_type)
        if spec is None:
            raise ValueError(
                f"unknown gate type: {gate_type!r}（可用: {sorted(self._specs)}；"
                "goal 类由轮次目标槽承载，不走配置层）"
            )
        return spec


def compile_gates(specs: List[Dict[str, Any]], catalog: GateCatalog = None) -> List[StopGate]:
    """把声明式配置编译为 gate 实例列表（按 priority 排序）。

    原子语义：先全量校验，任何一个非法即抛错且不产出任何实例。
    """
    catalog = catalog or GateCatalog()
    # 1) 全量校验
    validated: List[tuple] = []
    for i, item in enumerate(specs or []):
        gate_type = (item or {}).get("type", "")
        spec = catalog.get_spec(gate_type)
        try:
            params = spec.params_model(**(item.get("params") or {}))
        except ValidationError as e:
            raise ValueError(
                f"gate[{i}] {gate_type!r} 参数非法: {e}"
            ) from e
        validated.append((spec, params))

    # 2) 构建（校验全过才走到这里）
    gates = [spec.build(params.model_dump()) for spec, params in validated]
    gates.sort(key=lambda g: g.priority)
    return gates
