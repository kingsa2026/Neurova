# -*- coding: utf-8 -*-
"""工具定义三投影的目录层（实施计划项 3；本模块只做**投影**，不定义任何工具）。

## 三投影是什么

一条工具定义（`ToolDef`）向三个消费面投影，改一处四面一致：

1. **schema 投影**：`args_schema`（JSON Schema），供模型调用面与快照；
2. **权限投影**：`read_only` / `external_write` / `min_role` / `agent_scope`，供治理面；
3. **help 投影**：`render_help_line()` 把 ToolDef 渲染成提示词/文档里的工具条目。

## 单一事实源边界（教义第 6 条）

工具定义的**事实源仍是** `neurova/builtin_tools.py` 的声明位
（`_BUILTIN_SCHEMAS` 的 description/parameters、`capability` 声明、
`MAIN_AGENT_ONLY_TOOLS` 剔除集）。本模块**从声明位推导** `ToolDef`，
不重写、不另存任何工具定义；`all_tool_defs()` 是盘点投影的读侧。

## external_write 的当前口径

先沿用「非只读即记账」的保守口径（`external_write = not read_only`），
与项 2（工具调用先记账）的消费判据对齐；**不新造外部写名单**。待项 2
落地细化「外部副作用」判定时，只改这里的推导，消费方读数不变。

## 快照门

`build_snapshot()` 输出排序稳定、可重复生成的目录快照；
`contracts/tool_catalog.json` 是它的落盘件，`scripts/check_tool_catalog.py`
重新推导并 diff——不同步快照的任何工具面变更都会红。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = [
    "ToolDef",
    "all_tool_defs",
    "get_tool_def",
    "build_snapshot",
    "dump_snapshot",
    "render_help_line",
    "HELP_PROJECTION_SAMPLE_TOOL",
]

#: help 投影迁移样例工具（项 3 第二步：其余存量工具按域分批迁，不强制一次到位）。
HELP_PROJECTION_SAMPLE_TOOL = "context_status"


@dataclass(frozen=True)
class ToolDef:
    """一条内置工具的目录定义（从 builtin_tools 声明位推导，缺省即最保守）。

    Attributes:
        name: 工具注册名（与 ``get_registered_tool_names()`` 同一名册）。
        description: 工具描述（声明位原文，help 投影的取材）。
        args_schema: 参数 JSON Schema（声明位 ``parameters`` 的**副本**）。
        read_only: 只读。取自并行能力声明 ``capability.readOnly``；
            未声明 = False（最保守，与 ``core/tool_capability.py`` 缺省一致）。
        external_write: 外部写判定。当前口径：非只读即记账（见模块 docstring）。
        min_role: 角色门槛。当前仓内无工具级角色体系，缺省 None = 不设限
            （不新造名单；待权限体系落地再在此投影）。
        agent_scope: 使用者范围。"all" = 主/成员代理皆可用；
            "main_only" = 主代理专属（``MAIN_AGENT_ONLY_TOOLS`` 的投影）。
    """

    name: str
    description: str
    args_schema: Dict[str, Any]
    read_only: bool
    external_write: bool
    min_role: Optional[str] = None
    agent_scope: str = "all"


def all_tool_defs() -> List[ToolDef]:
    """盘点投影：builtin_tools 声明位 → ToolDef 名册（按名排序，稳定可重复）。

    惰性 import builtin_tools：本模块被 help 渲染路径调用时才装载事实源，
    与「深模块依赖注入」的装配纪律一致，也避免把 builtin_tools 拖进本模块
    的 import 期。
    """
    from neurova.builtin_tools import (
        MAIN_AGENT_ONLY_TOOLS,
        get_builtin_tool_capability,
        get_builtin_tool_params,
        get_registered_tool_names,
    )

    defs: List[ToolDef] = []
    for name in get_registered_tool_names():
        schema = get_builtin_tool_params(name) or {}
        capability = get_builtin_tool_capability(name)
        readOnly = bool(capability is not None and capability.readOnly)
        argsSchema = schema.get("parameters")
        if not isinstance(argsSchema, dict):
            argsSchema = {"type": "object", "properties": {}}
        defs.append(
            ToolDef(
                name=name,
                description=str(schema.get("description", "") or ""),
                args_schema=copy.deepcopy(argsSchema),
                read_only=readOnly,
                external_write=not readOnly,
                min_role=None,
                agent_scope="main_only" if name in MAIN_AGENT_ONLY_TOOLS else "all",
            )
        )
    return defs


def get_tool_def(tool_name: str) -> Optional[ToolDef]:
    """按名取一条 ToolDef；非内置工具返回 None。"""
    for defn in all_tool_defs():
        if defn.name == tool_name:
            return defn
    return None


def build_snapshot() -> Dict[str, Any]:
    """目录快照（排序稳定、可重复生成；不写时间戳/随机量）。

    ``tools`` 按 name 升序（``get_registered_tool_names()`` 本身有序）；
    序列化经 :func:`dump_snapshot` 固定排序键与缩进，同一代码树逐字节一致。
    """
    defs = all_tool_defs()
    return {
        "schema": 1,
        "source": "neurova.builtin_tools._BUILTIN_SCHEMAS",
        "tool_count": len(defs),
        "tools": [
            {
                "name": defn.name,
                "description": defn.description,
                "args_schema": defn.args_schema,
                "read_only": defn.read_only,
                "external_write": defn.external_write,
                "min_role": defn.min_role,
                "agent_scope": defn.agent_scope,
            }
            for defn in defs
        ],
    }


def dump_snapshot(snapshot: Dict[str, Any]) -> str:
    """快照规范序列化：固定排序键 + 固定缩进 + UTF-8 文本（逐字节可复现）。"""
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def render_help_line(defn: ToolDef, *, with_params: bool = True, desc_limit: Optional[int] = None) -> str:
    """help 投影：把 ToolDef 渲染成提示词「可用工具」段里的一行。

    格式与 ``orchestrator.render_tools_description`` 的存量 ``_line`` 逐字节
    一致（迁移零漂移）；taskName* 执行摘要参数与 ``to_openai_format()`` 走
    **同一注入单源**（``get_task_name_param_defs()``），不另写一份。

    Args:
        defn: 工具目录定义。
        with_params: 是否附参数段（预算降级时先丢参数段）。
        desc_limit: description 截断上限（字符；超限加省略号）。
    """
    from neurova.builtin_tools import get_task_name_param_defs

    desc = defn.description
    if desc_limit is not None and len(desc) > desc_limit:
        desc = desc[:desc_limit] + "…"
    params_desc = ""
    if with_params:
        props = dict(defn.args_schema.get("properties") or {})
        for paramName, paramDef in get_task_name_param_defs().items():
            props.setdefault(paramName, dict(paramDef))
        required = defn.args_schema.get("required") or []
        if props:
            param_list = [f"{k}{'(必填)' if k in required else ''}" for k in props]
            params_desc = f" — 参数: {', '.join(param_list)}"
    return f"- **{defn.name}**: {desc}{params_desc}"
