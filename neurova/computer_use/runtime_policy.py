"""桌面运行权限策略

决定 computer_* 动作"在哪跑 / 要不要先问用户"，与既有 governance 内容裁决**组合**
（governance 先跑 DENY/ASK，本策略是用户选的桌面运行姿态，叠加其上）。

四档（延伸）：
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

# ── 三档成员资格：**从工具自己的声明投影**，不在这里持手写名单 ──────────
# 本模块曾是三条手写名字表（READ_ONLY_TOOLS / HIGH_RISK_TOOLS /
# REMOTE_COMMAND_TOOLS）。三条各自承担一个完全可由声明推导的事实，而名单与声明面
# 之间**没有任何对账机制**：新增一个 computer_* 工具时声明面会变、名字表不会，
# 两处不一致也不会有任何红。这与并行轴旧名单同根因（那份旧名单里混着两个不存在
# 的名字，覆盖缺口只能靠人记）。
#
# 故成员资格下沉到产生该事实的地方——各工具的 schema 声明位：
#
#   档位   成员资格读谁                         声明处
#   low    `capability.readOnly`（并行轴同一份）  builtin_tools 各工具
#   high   `arbitrary_command`（任意命令语义）     同上
#   remote `remote_execution`（动作落远端）        同上
#
# 取数一律走下面三个 `desktop*Tools()` 出口，调用点不再各持一份集合。
# **判据**：tests/unit/computer_use/test_desktop_policy_projection.py 逐名复算
# 「清单 == 声明面投影」（含反向控制：改声明即改读数）。

#: 桌面工具面（前缀）。本模块的裁决只谈这一族——`classify_risk` 对族外名字
#: 一律回中档（保持既有语义：它答的是"这个桌面动作多危险"，不是通配分类器）。
_DESKTOP_PREFIX = "computer_"


def _desktopDeclaredNames() -> set:
    """注册面里 `computer_*` 的全体名字（声明面的取数基线）。"""
    from neurova.builtin_tools import get_registered_tool_names

    return {
        name for name in get_registered_tool_names() if name.startswith(_DESKTOP_PREFIX)
    }


def desktopReadOnlyTools() -> frozenset:
    """只读（无投递语义）桌面工具：任何模式直接放行。

    成员 = 桌面面里**自己声明了只读**的工具（`capability.readOnly`）。
    与并行轴读同一份声明，但两条轴问的不是同一件事：这里问"任何档都直接放行
    是否安全"，那里问"两个调用同时跑会不会互踩"（桌面读族在并行轴上恒串行，
    正是两件事的实例）。
    """
    from neurova.builtin_tools import get_builtin_tool_capability

    return frozenset(
        name
        for name in _desktopDeclaredNames()
        if (cap := get_builtin_tool_capability(name)) is not None and cap.readOnly
    )


def desktopHighRiskTools() -> frozenset:
    """高风险桌面工具：会让调用者文本获得任意命令执行语义。

    成员 = 声明了 `arbitrary_command` 的桌面工具。**刻意不绑 `sandbox_required`**：
    那条轴问"要不要真隔离执行"（P2-15），与本轴不同轴；撤掉沙箱要求不该让一个
    仍能执行任意命令的动作降成中档。
    """
    from neurova.builtin_tools import listBuiltinToolsWithFlag

    return frozenset(listBuiltinToolsWithFlag("arbitrary_command")) & _desktopDeclaredNames()


def desktopRemoteExecutionTools() -> frozenset:
    """在**远端**机器执行动作的桌面工具。

    它们本身已在远端跑，"进沙箱"对其无意义——只有审核档需要人工确认，其余档
    直接放行。成员 = 声明了 `remote_execution` 的桌面工具；与高危档**不互为别名**
    （本机 shell 高危但非远端，远端执行也未必是任意命令）。
    """
    from neurova.builtin_tools import listBuiltinToolsWithFlag

    return frozenset(listBuiltinToolsWithFlag("remote_execution")) & _desktopDeclaredNames()


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
    """桌面动作的风险档（三档，成员全部来自声明面投影）。"""
    if tool_name in desktopReadOnlyTools():
        return "low"
    if tool_name in desktopHighRiskTools():
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
    if tool_name in desktopRemoteExecutionTools():
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
