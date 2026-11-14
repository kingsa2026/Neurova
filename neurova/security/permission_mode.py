"""权限模式语义化（P1-4）：plan/build/edit/yolo/guarded（+auto 预留）。

模式语义（落到治理裁决上，只收敛、不放宽 DENY/SANDBOX）：
- PLAN：只读面放行，非只读工具的 ALLOW 收成 ASK（规划态不改世界）；
- BUILD：默认态，治理裁决原样；
- EDIT：工作区文件编辑三工具（file_write/file_create/file_edit）ASK→ALLOW，
  其余（命令/删除）不享受；
- YOLO：ASK→ALLOW（拒绝/沙箱裁决恒不动）；
- GUARDED：裁决不变，但语法级危险门强制生效（设置被关也开）；
- AUTO：预留位，诚实按 BUILD 走（不伪装智能）。

解析优先级：继承上下文（子代理，ContextVar 随派生任务传播）>
治理设置 per-agent 覆写（permission_mode_overrides）> 默认 BUILD。
限制型父模式（plan/guarded）对子代理**只收窄不升级**。
"""

from __future__ import annotations

import contextvars
import enum
from contextlib import contextmanager
from typing import Optional


class PermissionMode(str, enum.Enum):
    PLAN = "plan"
    BUILD = "build"
    EDIT = "edit"
    YOLO = "yolo"
    GUARDED = "guarded"
    AUTO = "auto"  # 预留：未实现，按 BUILD 走


VALID_MODE_VALUES = frozenset(m.value for m in PermissionMode)

#: 限制强度序（大=更严）：限制型父模式据此把子代理的宽模式压回来
_STRICTNESS = {
    PermissionMode.PLAN: 4,
    PermissionMode.GUARDED: 3,
    PermissionMode.BUILD: 2,
    PermissionMode.EDIT: 1,
    PermissionMode.YOLO: 0,
}

#: edit 模式免确认面：工作区文件编辑三件套（删除不享受——删除是破坏性操作）
FILE_EDIT_TOOLS = frozenset({"file_write", "file_create", "file_edit"})

#: 子代理继承的父模式（spawn 时置入，随任务上下文传播到子代理的每次治理预检）
_INHERITED_MODE: contextvars.ContextVar = contextvars.ContextVar(
    "neurova_inherited_permission_mode", default=None
)
#: 当前任务生效模式（治理预检置入，供治理侧读取，如 guarded 语法门强制）
_ACTIVE_MODE: contextvars.ContextVar = contextvars.ContextVar(
    "neurova_active_permission_mode", default=None
)


def inheritPermissionMode(parent: PermissionMode, child: PermissionMode) -> PermissionMode:
    """子代理模式继承：限制型父（plan/guarded）只收窄不升级；其余父模式不追紧。"""
    if parent in (PermissionMode.PLAN, PermissionMode.GUARDED):
        # child 比 parent 更宽（限制序更小）⇒ 压回 parent
        if _STRICTNESS[child] < _STRICTNESS[parent]:
            return parent
    return child


def _coerceMode(value) -> Optional[PermissionMode]:
    if isinstance(value, PermissionMode):
        return value
    if isinstance(value, str):
        try:
            return PermissionMode(value.strip().lower())
        except ValueError:
            return None
    return None


def resolvePermissionModeFor(agentId, settings=None) -> PermissionMode:
    """agent 级模式解析唯一出处（与 resolveRsiPhaseFor 同形）。

    overrides 命中该 agent（且条目合法）⇒ 覆写值；否则默认 BUILD。
    非法条目不炸装配：该 agent 回落 BUILD。
    """
    from neurova.security.governance_settings import load_governance_settings

    data = settings if settings is not None else load_governance_settings()
    overrides = data.get("permission_mode_overrides")
    if isinstance(overrides, dict):
        mode = _coerceMode(overrides.get(str(agentId or "")))
        if mode is not None:
            return mode
    return PermissionMode.BUILD


def resolveEffectivePermissionMode(agent) -> PermissionMode:
    """生效模式 = inherit(继承上下文, 该 agent 的设置覆写)。"""
    agentId = str(getattr(getattr(agent, "config", None), "agent_id", "") or "")
    own = resolvePermissionModeFor(agentId)
    inherited = _coerceMode(_INHERITED_MODE.get())
    if inherited is not None:
        return inheritPermissionMode(inherited, own)
    return own


@contextmanager
def inheritedModeScope(mode):
    """在作用域内声明「此时派生的子代理继承 mode」；随任务上下文传播。"""
    token = _INHERITED_MODE.set(_coerceMode(mode))
    try:
        yield
    finally:
        _INHERITED_MODE.reset(token)


def setActivePermissionMode(mode):
    """治理预检把本任务生效模式钉进上下文（供治理侧与诊断读取）。"""
    return _ACTIVE_MODE.set(_coerceMode(mode))


def effectiveModeInContext() -> Optional[PermissionMode]:
    return _coerceMode(_ACTIVE_MODE.get()) or _coerceMode(_INHERITED_MODE.get())


def contextForcesGuardedGate() -> bool:
    """当前上下文是否强制开语法级危险门（guarded 模式，设置关也开）。"""
    return effectiveModeInContext() == PermissionMode.GUARDED
