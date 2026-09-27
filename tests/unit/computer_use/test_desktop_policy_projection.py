# -*- coding: utf-8 -*-
"""桌面运行档的三条名单位居 → 声明面投影（Issue #271 M5 尾巴）。

## 根因

`computer_use/runtime_policy.py` 的 `READ_ONLY_TOOLS` / `HIGH_RISK_TOOLS` /
`REMOTE_COMMAND_TOOLS` 是**手写名字表**，各自承担一个完全可由工具自己的声明
推导的事实：

  名单                    它回答的问题                    应由谁回答
  READ_ONLY_TOOLS         这个动作会不会改变机器状态      capability.readOnly
  HIGH_RISK_TOOLS         这个动作会不会执行任意命令      arbitrary_command 声明
  REMOTE_COMMAND_TOOLS    这个动作是不是在远端机器执行    remote_execution 声明

后果不是"今天写错了"（实测三条当前恰好与声明面吻合），而是**没有任何机制保证
它明天还对**：新增一个 `computer_*` 工具时声明面会变、名字表不会，两处不一致
也不会有任何红。这与 M3 并行轴旧名单同根因（旧名单里被逮住两个幻名，覆盖缺口
无人可读）。

## 为什么 HIGH_RISK 不直接绑 `sandbox_required`

两条轴回答的不是同一个事实：`sandbox_required`（P2-15）问"要不要真隔离执行"，
桌面高危问"会不会执行任意命令"。它们当前在 `computer_*` 上成员恰好相同，但那是
**巧合**——按教义第 6 条不得把巧合当同源。本文件用
`test_highRiskDoesNotFollowSandboxRequired` 把这条钉成活判据：撤掉
`sandbox_required` 后高危成员必须不变。

## 等价迁移契约

本片是**零行为变化**的迁移：三条清单的成员与改动前逐名相同；11 个
`computer_*` × 4 个运行档的决策矩阵逐格相同（`test_decisionMatrixIsPinned`）。
"""

from __future__ import annotations

import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    BuiltinToolRegistry,
    get_builtin_tool_capability,
    get_registered_tool_names,
)
from neurova.computer_use import runtime_policy as rp
from neurova.computer_use.runtime_policy import classify_risk, decide_desktop

#: 桌面工具面（前缀判定）——判据侧的独立复算口径，不从被测量模块借
DESKTOP_PREFIX = "computer_"

#: 改动前的决策矩阵**逐格**（11 工具 × full/sandbox/review/auto）。
#: 本片是等价迁移：投影上线后每一格都必须与这里相同。
PINNED_DECISIONS = {
    "computer_screenshot": ("proceed", "proceed", "proceed", "proceed"),
    "computer_dom_snapshot": ("proceed", "proceed", "proceed", "proceed"),
    "computer_som_snapshot": ("proceed", "proceed", "proceed", "proceed"),
    "computer_click": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_click_element": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_click_mark": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_type": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_scroll": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_set_value": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_shell": ("proceed", "require_sandbox", "require_approval", "require_sandbox"),
    "computer_ssh_exec": ("proceed", "proceed", "require_approval", "proceed"),
}

MODES = ("full", "sandbox", "review", "auto")


def _desktopNames() -> set:
    """内置注册面里 `computer_*` 的名字（判据侧独立取数）。"""
    return {n for n in get_registered_tool_names() if n.startswith(DESKTOP_PREFIX)}


def _declaredReadOnly() -> set:
    """从声明位独立复算"只读"——不经 `runtime_policy` 的任何读取路径。"""
    out = set()
    for name in _desktopNames():
        cap = get_builtin_tool_capability(name)
        if cap is not None and cap.readOnly:
            out.add(name)
    return out


def _declaredFlag(key: str) -> set:
    """从声明位独立复算某个布尔声明键为 True 的桌面工具。"""
    return {
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if name.startswith(DESKTOP_PREFIX) and schema.get(key) is True
    }


def _patchCapability(monkeypatch, name: str, **changes) -> None:
    """改某工具声明的 `capability` 子键（逐字段覆盖，不动其余字段）。"""
    schema = _BUILTIN_SCHEMAS[name]
    merged = dict(schema.get("capability") or {})
    merged.update(changes)
    monkeypatch.setitem(schema, "capability", merged)


# ═══════════════════════════════════════════════════════════════
# 一、三条清单必须是声明面的**函数**，不是快照
# ═══════════════════════════════════════════════════════════════


class TestListsFollowTheDeclaration:
    """反向控制：改声明 → 清单读数跟着变。快照式名字表在这一组上必红。"""

    def test_readOnlyListFollowsCapabilityDeclaration(self, monkeypatch):
        assert "computer_screenshot" in rp.desktopReadOnlyTools()
        _patchCapability(monkeypatch, "computer_screenshot", readOnly=False)
        assert "computer_screenshot" not in rp.desktopReadOnlyTools(), (
            "只读清单没跟着 `capability.readOnly` 走——它是手写快照，"
            "新增工具时两处必然漂移且无人可读"
        )

    def test_highRiskListFollowsArbitraryCommandDeclaration(self, monkeypatch):
        assert "computer_click" not in rp.desktopHighRiskTools()
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_click"], "arbitrary_command", True)
        assert "computer_click" in rp.desktopHighRiskTools(), (
            "高危清单没跟着 `arbitrary_command` 声明走——它是手写快照"
        )

    def test_remoteExecutionListFollowsRemoteDeclaration(self, monkeypatch):
        assert "computer_shell" not in rp.desktopRemoteExecutionTools()
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_shell"], "remote_execution", True)
        assert "computer_shell" in rp.desktopRemoteExecutionTools(), (
            "远端清单没跟着 `remote_execution` 声明走——它是手写快照"
        )


# ═══════════════════════════════════════════════════════════════
# 二、两条轴不合并（HIGH_RISK ≠ sandbox_required，REMOTE ≠ HIGH_RISK）
# ═══════════════════════════════════════════════════════════════


class TestAxesAreNotAliased:
    """成员当前恰好重合，但重合是巧合——本组把"不是同一个事实"钉成机器判据。"""

    def test_highRiskDoesNotFollowSandboxRequired(self, monkeypatch):
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_shell"], "sandbox_required", False)
        assert "computer_shell" in rp.desktopHighRiskTools(), (
            "高危清单跟着 `sandbox_required` 走了——那是「要不要真隔离执行」轴"
            "（P2-15），与本轴问的「会不会执行任意命令」不是同一件事"
        )

    def test_remoteExecutionIsNotAliasedToHighRisk(self, monkeypatch):
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_ssh_exec"], "arbitrary_command", False)
        assert "computer_ssh_exec" not in rp.desktopHighRiskTools()
        assert "computer_ssh_exec" in rp.desktopRemoteExecutionTools(), (
            "远端清单跟着高危清单走了——「在远端执行」与「执行任意命令」是两条轴"
        )

    def test_declarationLandingOnNonDesktopToolIsIgnored(self, monkeypatch):
        """桌面档只谈 `computer_*` 适用面：给它面外的工具加声明不得改变读数。"""
        monkeypatch.setitem(_BUILTIN_SCHEMAS["run_code"], "arbitrary_command", True)
        monkeypatch.setitem(_BUILTIN_SCHEMAS["run_code"], "remote_execution", True)
        assert "run_code" not in rp.desktopHighRiskTools()
        assert "run_code" not in rp.desktopRemoteExecutionTools()
        assert "run_code" not in rp.desktopReadOnlyTools()


# ═══════════════════════════════════════════════════════════════
# 三、成员集合与声明面逐名咬合（判据不自证）
# ═══════════════════════════════════════════════════════════════


class TestMembersMatchDeclarationSurface:
    def test_listsEqualIndependentRecompute(self):
        assert rp.desktopReadOnlyTools() == _declaredReadOnly()
        assert rp.desktopHighRiskTools() == _declaredFlag("arbitrary_command")
        assert rp.desktopRemoteExecutionTools() == _declaredFlag("remote_execution")

    def test_currentMembersArePinned(self):
        """当前成员逐名钉住——成员变了必须是有意的，不能静默漂移。"""
        assert rp.desktopReadOnlyTools() == {
            "computer_screenshot",
            "computer_dom_snapshot",
            "computer_som_snapshot",
        }
        assert rp.desktopHighRiskTools() == {"computer_shell", "computer_ssh_exec"}
        assert rp.desktopRemoteExecutionTools() == {"computer_ssh_exec"}

    def test_projectedMembersAreRegisteredTools(self):
        """投影成员必须是注册面真名——幻名在这条上必红（M3 旧名单的教训）。"""
        registered = set(get_registered_tool_names())
        for name in (
            rp.desktopReadOnlyTools()
            | rp.desktopHighRiskTools()
            | rp.desktopRemoteExecutionTools()
        ):
            assert name in registered, f"{name} 不是注册工具名"


# ═══════════════════════════════════════════════════════════════
# 四、等价迁移契约：决策矩阵逐格不变 + 模型可见面零变化
# ═══════════════════════════════════════════════════════════════


class TestZeroBehaviourChange:
    def test_decisionMatrixIsPinned(self):
        """11 个桌面工具 × 4 档逐格钉住；覆盖面变化也在本条上红。"""
        for name, expected in PINNED_DECISIONS.items():
            got = tuple(decide_desktop(m, name)["action"] for m in MODES)
            assert got == expected, f"{name} 的决策矩阵变了：{got} != {expected}"
        assert set(PINNED_DECISIONS) == _desktopNames(), (
            "桌面工具面变了而矩阵没跟着扩——新增 computer_* 工具必须逐格补钉"
        )

    def test_riskBucketsArePinned(self):
        for name in rp.desktopReadOnlyTools():
            assert classify_risk(name) == "low", name
        for name in rp.desktopHighRiskTools():
            assert classify_risk(name) == "high", name
        for name in _desktopNames() - rp.desktopReadOnlyTools() - rp.desktopHighRiskTools():
            assert classify_risk(name) == "medium", name

    def test_unknownToolKeepsMediumBucket(self):
        """反向控制：非桌面名字恒 medium（本轴不越界裁决其它工具）。"""
        for name in ("memory_search", "run_code", "exec_command", "no_such_tool"):
            assert classify_risk(name) == "medium", name

    def test_declarationKeysDoNotReachModelSurface(self):
        """声明位不进 `to_openai_format()`——模型可见面零变化。"""
        registry = BuiltinToolRegistry()
        for name in ("computer_shell", "computer_ssh_exec", "computer_screenshot"):
            payload = registry.get_tool(name).to_openai_format()["function"]
            for key in ("capability", "arbitrary_command", "remote_execution", "sandbox_required"):
                assert key not in payload, f"{name} 的声明键 {key} 泄漏进模型可见面"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
