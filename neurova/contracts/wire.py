# -*- coding: utf-8 -*-
"""wire 契约派生单源层：全部形状从代码事实源现场派生，不手抄、不落第二份。

## 为什么有这一层

wire 契约的形状事实散在多处代码里（builtin_tools 声明位、SubAgentRun.to_dict、
swarm 事件写入调用点），生成脚本（check_tool_catalog）与守卫测试
（wire_backward_compat）原本各自取形。本层把它们收口成**一个读侧**：
契约形状只在这里派生一次，消费方一律从本层取——不复制形状、不造第二事实源。

## 事实源与派生方向

| 读侧函数 | 事实源 | 派生方式 |
|----------|--------|----------|
| toolCatalogSnapshot / toolCatalogEntries | builtin_tools 声明位 | 经 neurova.tools.catalog.build_snapshot 投影（本层不重复推导） |
| runProjectionKeys | SubAgentRun.to_dict | 构造最小实例取真实键集 |
| eventTypes | swarm_event_log 的写入调用点 | 扫描调用点源码里的事件类型字面量 |
| continueSubagentModes | builtin_tools 的 continue_subagent schema | 取 parameters.properties.mode.enum |

## fail-closed

任何派生失败（事实源缺失、形状为空、调用点不可读）一律显式抛 RuntimeError，
绝不返回静默空表——空契约比没有契约更危险，它会让 verify-diff 门与守卫测试假绿。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

__all__ = [
    "toolCatalogSnapshot",
    "toolCatalogEntries",
    "runProjectionKeys",
    "eventTypes",
    "continueSubagentModes",
]

# 事件类型词值的写入调用点（相对 neurova 包根）。swarm_event_log 本身只收
# eventType 字符串参数、不定义词值；全部词值都由这些调用点以字面量传入，
# 因此"从 swarm_event_log 的事件类型词值派生"落地为"从它的全部写入调用点
# 派生"。新增事件写入点文件时须登记于此（漏登记 = 词值集合缺角）。
_EVENT_CALL_SITE_MODULES: Tuple[str, ...] = (
    "agent/swarm.py",
    "agent/swarm_support.py",
    "agent/neuacp/acp_member.py",
)

# 匹配三类事件写入调用形态的事件类型字面量：
#   self._logRunEvent(run, "spawned", {...})      （swarm.SwarmManager 方法）
#   logEvent(run, "tool_call", redacted)          （acp_member.bindRun 注入侧）
#   appendRunEvent(run.subagent_id, "status_changed", ...)（跨行调用也命中）
_EVENT_TYPE_CALL_RE = re.compile(
    r"(?:_logRunEvent|logEvent|appendRunEvent)\s*\(\s*"
    r"[A-Za-z_][\w.]*\s*,\s*['\"]([a-z_]+)['\"]",
    re.S,
)


def _packageRoot() -> Path:
    """neurova 包根目录（本模块位于 <root>/contracts/wire.py）。"""
    return Path(__file__).resolve().parents[1]


def toolCatalogSnapshot() -> Dict[str, Any]:
    """完整工具目录快照（schema/source/tool_count/tools），verify-diff 门的比对基准。

    事实源是 builtin_tools 声明位；排序稳定、可重复生成的投影在
    neurova.tools.catalog.build_snapshot。本函数是它的 wire 消费入口，
    不重复推导、不改写形状。
    """
    from neurova.tools.catalog import build_snapshot

    snapshot = build_snapshot()
    entries = snapshot.get("tools") if isinstance(snapshot, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("工具目录派生为空：build_snapshot 未返回任何条目（事实源失效）")
    return snapshot


def toolCatalogEntries() -> List[Dict[str, Any]]:
    """工具目录条目列表（快照的 tools 字段），按 name 升序稳定排序。"""
    return toolCatalogSnapshot()["tools"]


def runProjectionKeys() -> frozenset:
    """SubAgentRun.to_dict 的 wire 投影键集（构造最小实例取真实键集）。

    键集是 run 投影（前端 run 卡/台账/协作档案/候选投影）的 wire 契约：
    只增不减，消费方按这些键取数。期望值一律从这里取，不再手抄键清单。
    """
    from neurova.agent.swarm_support import SubAgentRun

    probe = SubAgentRun(subagent_id="contract-probe", depth=1)
    keys = frozenset(probe.to_dict().keys())
    if not keys:
        raise RuntimeError("run 投影键集派生为空：SubAgentRun.to_dict 未产出任何键")
    return keys


def eventTypes() -> Tuple[str, ...]:
    """swarm 事件账本的事件类型词值全集（去重、按名排序、可重复）。

    派生自 swarm_event_log 的全部写入调用点源码（见 _EVENT_CALL_SITE_MODULES）；
    事件 record 的 ``type`` 字段取值域以此为准。
    """
    types = set()
    for rel in _EVENT_CALL_SITE_MODULES:
        path = _packageRoot() / rel
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"事件类型派生失败：调用点源码不可读 {path}：{exc}") from exc
        types.update(_EVENT_TYPE_CALL_RE.findall(source))
    if not types:
        raise RuntimeError("事件类型派生为空：调用点里没扫到任何事件类型字面量")
    return tuple(sorted(types))


def continueSubagentModes() -> Tuple[str, ...]:
    """continue_subagent 的 mode 枚举（从 builtin_tools schema 派生，保序）。

    enum 顺序是 schema 声明的一部分（模型可见面），此处原样保留声明顺序。
    """
    from neurova.builtin_tools import get_builtin_tool_params

    schema = get_builtin_tool_params("continue_subagent")
    if not schema:
        raise RuntimeError("continue_subagent schema 缺失：mode 枚举无从派生")
    enum = (
        (schema.get("parameters") or {})
        .get("properties", {})
        .get("mode", {})
        .get("enum")
    )
    if not enum:
        raise RuntimeError("continue_subagent schema 未声明 mode.enum：枚举无从派生")
    return tuple(enum)
