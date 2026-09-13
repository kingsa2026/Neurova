"""桌面运行权限策略（CUA Phase 3 扩展 RS 生产触发层，用户可配 4 档）

决定 computer_* 动作"在哪跑 / 要不要先问用户"，与既有 governance 内容裁决**组合**
（governance 先跑 DENY/ASK，本策略是用户选的桌面运行姿态，叠加其上）。

四档（docs/Neurova_CUA_远程会话平面立项_2026-09-12.md 延伸）：
- full   完全放开：本机执行（= 现状，默认，零回归），仅受 governance 约束
- sandbox 沙箱运行：所有变更动作必须在隔离桌面会话执行；无活动会话 → 拒
- review 审核模式：所有变更动作需用户在交互面板同意/拒绝（走 ApprovalManager）
- auto   自动模式：低风险自动执行；中/高风险进沙箱（agent 自主分级）

只读动作（截图/快照）任何档都直接放行——它们无副作用。
"""

from __future__ import annotations

import contextvars
from enum import Enum
from typing import Any, Dict

# 审批重放/持久授权旁路：skip_governance=True 的执行（用户已批准）不再触发运行门，
# 否则审核模式批准后重放会再次铸审批形成死循环。
_gate_bypass: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "desktop_runtime_gate_bypass", default=False
)


def set_gate_bypass(value: bool):
    return _gate_bypass.set(bool(value))


def reset_gate_bypass(token: Any) -> None:
    try:
        _gate_bypass.reset(token)
    except Exception:  # noqa: BLE001
        pass


def is_gate_bypassed() -> bool:
    return _gate_bypass.get()

# 只读（无投递语义）桌面工具：任何模式直接放行
READ_ONLY_TOOLS = frozenset({
    "computer_screenshot",
    "computer_dom_snapshot",
    "computer_som_snapshot",
})
# 高风险：任意命令执行
HIGH_RISK_TOOLS = frozenset({"computer_shell", "computer_ssh_exec"})
# 远程命令工具：本身已在远端机器执行（Linux/macOS 走 SSH），"进沙箱"对其无意义——
# 只有 review 档需要人工确认，其余档直接放行。
REMOTE_COMMAND_TOOLS = frozenset({"computer_ssh_exec"})
# 其余 computer_* 变更动作 = 中风险


class DesktopRuntimeMode(str, Enum):
    FULL = "full"
    SANDBOX = "sandbox"
    REVIEW = "review"
    AUTO = "auto"


class DesktopAction(str, Enum):
    PROCEED = "proceed"            # 直接执行
    REQUIRE_SANDBOX = "require_sandbox"  # 须在隔离会话执行
    REQUIRE_APPROVAL = "require_approval"  # 须用户审批


def classify_risk(tool_name: str) -> str:
    if tool_name in READ_ONLY_TOOLS:
        return "low"
    if tool_name in HIGH_RISK_TOOLS:
        return "high"
    return "medium"


def decide_desktop(mode: str, tool_name: str) -> Dict[str, Any]:
    """纯策略函数：给定运行档 + 工具 → 决策。可独立测试，无副作用。"""
    risk = classify_risk(tool_name)
    try:
        m = DesktopRuntimeMode(mode)
    except ValueError:
        m = DesktopRuntimeMode.FULL  # 未知档回退最宽松（= 现状），不误伤

    if risk == "low":
        return {"action": DesktopAction.PROCEED.value, "risk": risk, "reason": "只读动作直接放行"}

    # 远程命令（SSH）：本身已在远端机器执行，"进沙箱"无意义——仅 review 档要人工确认
    if tool_name in REMOTE_COMMAND_TOOLS:
        if m == DesktopRuntimeMode.REVIEW:
            return {"action": DesktopAction.REQUIRE_APPROVAL.value, "risk": risk, "reason": "审核模式：远程命令须用户确认"}
        return {"action": DesktopAction.PROCEED.value, "risk": risk, "reason": "远程命令已在远端执行，直接放行"}

    if m == DesktopRuntimeMode.FULL:
        return {"action": DesktopAction.PROCEED.value, "risk": risk, "reason": "完全放开：本机执行"}
    if m == DesktopRuntimeMode.SANDBOX:
        return {"action": DesktopAction.REQUIRE_SANDBOX.value, "risk": risk, "reason": "沙箱运行档：变更动作须隔离会话"}
    if m == DesktopRuntimeMode.REVIEW:
        return {"action": DesktopAction.REQUIRE_APPROVAL.value, "risk": risk, "reason": "审核模式：变更动作须用户确认"}
    # AUTO：低→放行；中/高→沙箱
    return {"action": DesktopAction.REQUIRE_SANDBOX.value, "risk": risk, "reason": f"自动模式：{risk}风险进沙箱"}


# ── 运行档持久化（复用 app_settings advanced 段，热读无需重启）──────────

_MODE_KEY = "desktop_runtime_mode"


def get_runtime_mode() -> str:
    try:
        from neurova.core.app_settings import get_advanced_settings

        mode = get_advanced_settings().get(_MODE_KEY)
        if mode in {m.value for m in DesktopRuntimeMode}:
            return mode
    except Exception:  # noqa: BLE001
        pass
    return DesktopRuntimeMode.FULL.value


def set_runtime_mode(mode: str) -> bool:
    if mode not in {m.value for m in DesktopRuntimeMode}:
        return False
    try:
        from neurova.core.app_settings import save_app_settings

        save_app_settings("advanced", {_MODE_KEY: mode})
        return True
    except Exception:  # noqa: BLE001
        return False
