# -*- coding: utf-8 -*-
"""能力面「系统面」成员资格：由工具自己的声明补齐（Issue #271 M5 尾巴·第四命中点）。

## 根因（放大视角扫同契约消费方时逮到，本片新发现）

`skills/permissions.py` 的 `_CATEGORY_TOOLS["system"]` 是一份**手写名字表**，
只有 7 个成员：

    {"computer_shell", "computer_screenshot", "computer_click",
     "computer_type", "computer_scroll", "run_code", "spawn_subagent"}

而已归档的 M5 尾巴已证实：工具的"要不要真隔离执行"与"命令文本是否交给真 shell"
两条事实**可由工具自己的声明回答**（`sandbox_required` / `shell_dialect`，
见 PR #292）。本片实测该声明面照出的缺口有**实际后果**：

    有声明技能（permissions: {system: false}）下：
      computer_shell      → 拒（在名单里）          ← 名单生效
      computer_ssh_exec   → **放行**（不在名单里）  ← 声明了 sandbox_required + shell_dialect
      exec_command        → **放行**（不在名单里）  ← 声明了 sandbox_required + shell_dialect

`exec_command`（P0-3 会话式 shell，`shell=True` 跑真命令）与 `computer_ssh_exec`
（远端真 shell）都是**真命令执行面**，却在系统面外 ⇒ 一个声明了 `system: false`
的技能照样能调它们。这与并行轴旧名单、壳方言旧名单是同一根因的三个不同落点。

## 同类第二处：桌面族漏登

同一条"手写名单没跟上工具面"的漂移，在系统面里还有一处更直白的：

    computer_click_element / computer_set_value / computer_som_snapshot
    / computer_dom_snapshot / computer_click_mark

这 5 个都是 `computer_*` 桌面动作（后三个只读、前两个语义操作），却不在系统面内。
本片不把它们批量塞进名单，而是**按声明面推导**：有 `sandbox_required` 声明的
入系统面（真隔离语义），其余 `computer_*` 桌面动作另有归属口径。

## 处置口径

系统面 = **手写名单 ∪ 声明面投影**，两处各自承担它真能回答的那部分：

- 手写名单：`run_code` / `spawn_subagent` / 桌面动作族——这些没有"真 shell/真隔离"
  声明，但它们执行的是**本机系统动作**（改机器状态），故仍需显式登记；
- 声明面投影：`sandbox_required` 为真者——那是"这个工具要不要真隔离执行"的
  工具自己的承诺，系统面必须收它。

登记与投影都必须**恰等于**复算结果，由本文件逐名钉住。
"""

from __future__ import annotations

import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    get_registered_tool_names,
)
from neurova.skills.permissions import (
    SkillPermissions,
    _CATEGORY_TOOLS,
    tool_categories,
    tool_category,
)

#: 手写登记的**非声明面**系统工具（各自写明为什么必须显式登记）。
#: `run_code` / `computer_shell` 不在其中——它们自己也声明了 `sandbox_required`，
#: 故由声明面投影收入系统面（同一份事实不两处重复登记）。
REGISTERED_SYSTEM_TOOLS = {
    "spawn_subagent": "派生子代理（本机进程资源；无 sandbox_required 声明）",
}

#: 桌面动作族：会改变共享桌面状态，属系统面。
DESKTOP_SYSTEM_TOOLS = {
    "computer_screenshot",
    "computer_click",
    "computer_type",
    "computer_scroll",
    "computer_click_element",
    "computer_set_value",
    "computer_som_snapshot",
    "computer_dom_snapshot",
    "computer_click_mark",
}


def _declaredSandboxRequired() -> set:
    """从声明面独立复算：声明了必须在真隔离下执行的工具。"""
    return {
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and schema.get("sandbox_required") is True
    }


# ═══════════════════════════════════════════════════════════════
# 一、声明面照出的缺口：真 shell 工具必须在系统面内
# ═══════════════════════════════════════════════════════════════


class TestDeclaredSandboxToolsAreInSystemFace:
    @pytest.mark.parametrize("name", ["computer_ssh_exec", "exec_command"])
    def test_realShellToolsAreSystemScoped(self, name):
        """真命令执行面必须在系统面内——否则 `system: false` 的技能照样能调。"""
        assert tool_category(name) == "system", (
            f"{name} 是真命令执行面（声明了 sandbox_required / shell_dialect），"
            "却不在系统面内 ⇒ 声明了 system=false 的技能仍可执行它"
        )

    def test_everySandboxRequiredToolIsSystemScoped(self):
        """声明面逐名咬合：凡声明了 sandbox_required 的，都必须在系统面内。"""
        missing = sorted(n for n in _declaredSandboxRequired()
                         if "system" not in tool_categories(n))
        assert missing == [], (
            f"这些工具声明了 sandbox_required（须真隔离执行），却不在系统面内：{missing}"
        )

    def test_declarationSurfaceIsNotEmpty(self):
        """反向锁：声明面确实有成员（空集会让上一条变成恒真）。"""
        assert _declaredSandboxRequired() >= {"computer_shell", "run_code"}


# ═══════════════════════════════════════════════════════════════
# 二、有实际后果：声明面外的工具真的被放行了
# ═══════════════════════════════════════════════════════════════


class TestBehaviourAfterClosure:
    def _lockedDown(self):
        """一个把系统面关掉的声明技能。"""
        return SkillPermissions.from_dict({
            "system": False, "network": False, "file": False, "model": False,
        })

    def test_systemFalseRefusesRealShellTools(self):
        p = self._lockedDown()
        for name in ("computer_ssh_exec", "exec_command", "computer_shell", "run_code"):
            assert p.allows_tool(name) is False, f"{name} 在 system=false 下仍被放行"

    def test_platformToolsStayUnconstrained(self):
        """反向锁：平台能力（记忆/规划）不受能力面约束，不得被本片误收紧。"""
        p = self._lockedDown()
        for name in ("memory_search", "planning", "update_plan"):
            assert p.allows_tool(name) is True, f"{name} 是平台能力，不该被系统面约束"

    def test_systemTrueStillAllows(self):
        p = SkillPermissions.from_dict({"system": True, "network": False, "file": False})
        for name in ("computer_ssh_exec", "exec_command", "run_code"):
            assert p.allows_tool(name) is True, f"{name} 在 system=true 下应放行"


# ═══════════════════════════════════════════════════════════════
# 三、成员集合逐名钉住（判据不自证）
# ═══════════════════════════════════════════════════════════════


class TestSystemFaceMembership:
    def test_membersAreRegisteredTools(self):
        registered = set(get_registered_tool_names())
        for name in _CATEGORY_TOOLS["system"]:
            assert name in registered, f"{name} 不是注册工具名（幻名）"

    def test_registeredNonDeclarationPartIsPinned(self):
        """手写那部分逐名钉住：非声明面成员必须恰是登记表里的名字。"""
        registered_only = _CATEGORY_TOOLS["system"] - _declaredSandboxRequired()
        expected = set(REGISTERED_SYSTEM_TOOLS) | DESKTOP_SYSTEM_TOOLS
        assert registered_only == expected, (
            "系统面的手写部分漂了："
            f"多出={sorted(registered_only - expected)}"
            f"，少了={sorted(expected - registered_only)}"
        )

    def test_desktopActionsAreSystemScoped(self):
        for name in DESKTOP_SYSTEM_TOOLS:
            assert tool_category(name) == "system", f"{name} 是桌面系统动作，应属系统面"

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
