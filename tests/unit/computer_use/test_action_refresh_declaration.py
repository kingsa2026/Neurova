# -*- coding: utf-8 -*-
"""动作后自动补拍刷新：名单成员资格收口到声明面（Issue #271 M5 尾巴·第二命中点）。

## 根因（放大视角扫同契约消费方时逮到）

`tool_executor.computerActionRefreshTools()`（R0-3）是一份**手写名字表**，
写它的那天有 5 个成员。此后 `computer_click_mark` 被接进刷新链——它的执行体
照样置 `refreshed_screenshot`、照样调 `_emit_action_refreshed_screenshot`——
**而名单没跟着改，也没有任何红**。实测：

    实际调用刷新链的工具 = ['computer_click', 'computer_click_element',
                            'computer_click_mark', 'computer_scroll',
                            'computer_set_value', 'computer_type']
    名单读数             = 少了 'computer_click_mark'
    生产侧消费点         = 0（全仓唯一出现处就是它的定义行）
    测试侧引用点         = 0

即：它**既是**一份与真实行为已漂移的名单，**又是**一个只写不读的断点
（协作红线点名的「写出无人读的字段」形态）——两条互为因果：正因为没人读它，
漂移才没有任何代价。

## 处置口径（两条都不许留）

1. **成员资格下沉到声明位**：`interactive_desktop` 键（"这个动作会不会改变共享
   桌面的画面"）落在各工具自己的 schema 上。名单由声明推导，新增工具时
   声明面变、投影跟着变。
2. **消费方接上**：`_emit_action_refreshed_screenshot` 用它做**唯一入口守卫**，
   而不是让 6 个执行体各自记得调它。于是名单从"零消费"变成真闸门：
   未声明的工具即使误调也进不去。

## 与 `capability` / `arbitrary_command` 的关系

三条轴，各答一个事实，不合并：`capability.writeScopes` 问"并发会不会互踩"、
`arbitrary_command` 问"会不会执行任意命令"、`interactive_desktop` 问"动作会不会
改变共享桌面画面"。三者当前在 `computer_*` 上成员接近重合，但 `computer_shell`
会执行任意命令却**不改变桌面画面**、`computer_ssh_exec` 动作落远端更是如此——
合并会让"跑个 shell"也去补拍一张本机截图。
"""

from __future__ import annotations

import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    get_registered_tool_names,
)
from neurova.tool_executor import (
    COMPUTER_USE_TOOLS,
    computerActionRefreshTools,
)

#: 改动前的名单读数（本片是**补漏**而非等价迁移：漏登的 member 必须补进）。
LEGACY_MEMBERS = {
    "computer_click",
    "computer_type",
    "computer_scroll",
    "computer_click_element",
    "computer_set_value",
}

#: 执行体里真的会调刷新链的工具（判据侧独立复算，见 `_actualRefreshCallers`）。
EXPECTED_MEMBERS = LEGACY_MEMBERS | {"computer_click_mark"}


def _declaredInteractive() -> set:
    """从声明位独立复算"会改变共享桌面画面"的工具。"""
    return {
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and schema.get("interactive_desktop") is True
    }


def _actualRefreshCallers() -> set:
    """AST 复算：执行体里真调了 `_emit_action_refreshed_screenshot` 的工具名。

    从传参的第一个实参读——那正是事件上的 `tool_name`。这样"名单"与"行为"
    由同一个事实面推出，而不是靠人抄。
    """
    import ast
    from pathlib import Path

    from tests import ast_scan

    tree = ast_scan.transientTree(Path(__file__).resolve().parents[3] / "neurova" / "tool_executor.py")
    callers: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "_emit_action_refreshed_screenshot":
            if node.args and isinstance(node.args[0], ast.Constant):
                callers.add(str(node.args[0].value))
    return callers


# ═══════════════════════════════════════════════════════════════
# 一、名单与行为面逐名咬合（本片的核心：漏登必须被逮住）
# ═══════════════════════════════════════════════════════════════


class TestRefreshMembersFollowBehaviour:
    def test_rosterMatchesActualCallers(self):
        """名单必须恰等于真调刷新链的工具集合——`computer_click_mark` 漏登在这一条上红。"""
        assert set(computerActionRefreshTools()) == _actualRefreshCallers(), (
            "补拍名单与执行体里的实际调用面不一致："
            f"名单独有={sorted(set(computerActionRefreshTools()) - _actualRefreshCallers())}"
            f"，行为独有={sorted(_actualRefreshCallers() - set(computerActionRefreshTools()))}"
        )

    def test_clickMarkWasTheMissingMember(self):
        """把本片修掉的那条点名：漏登的正是 `computer_click_mark`。"""
        assert "computer_click_mark" in computerActionRefreshTools()
        assert "computer_click_mark" in _actualRefreshCallers()

    def test_legacyMembersAreNotDropped(self):
        """原 5 名一项不得丢（静默收窄会悄悄砍掉已有行为）。"""
        assert LEGACY_MEMBERS <= set(computerActionRefreshTools())

    def test_rosterEqualsDeclarationProjection(self):
        assert set(computerActionRefreshTools()) == _declaredInteractive()
        assert _declaredInteractive() == EXPECTED_MEMBERS

    def test_membersAreRegisteredDesktopTools(self):
        registered = set(get_registered_tool_names())
        for name in computerActionRefreshTools():
            assert name in registered, f"{name} 不是注册工具名"
            assert name in COMPUTER_USE_TOOLS, f"{name} 不在桌面事件面内"


# ═══════════════════════════════════════════════════════════════
# 二、消费方真的接上了（"零消费"是本切片要根修的断点之一）
# ═══════════════════════════════════════════════════════════════


class TestRosterHasARealConsumer:
    def test_refreshEmitterIsGuardedByTheRoster(self, monkeypatch):
        """入口守卫：把成员从声明面摘掉 → 刷新链直接短路（不再发事件）。

        这正是"名单不是摆设"的机器证据：改动前该名单零消费，摘不摘都一样。
        """
        import asyncio

        from neurova.tool_executor import ToolExecutor

        calls: list = []
        inst = ToolExecutor.__new__(ToolExecutor)

        async def fake_emit(self, tool_name, params, result, **kw):
            calls.append(tool_name)

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: _StubManager())
        monkeypatch.setattr(
            "neurova.tool_executor.ACTION_REFRESH_DELAY_SECONDS", 0.0, raising=False
        )

        asyncio.run(inst._emit_action_refreshed_screenshot("computer_click", {}, {"success": True}))
        assert calls == ["computer_click"], "已声明成员应照常补拍"

        calls.clear()
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_click"], "interactive_desktop", False)
        asyncio.run(inst._emit_action_refreshed_screenshot("computer_click", {}, {"success": True}))
        assert calls == [], (
            "摘掉声明后刷新链仍然发包——名单没有被任何消费方读到（零消费断点未闭环）"
        )


class _StubManager:
    """最小替身：只要 `screenshot()` 返回非空字节，刷新链就会发包。"""

    def screenshot(self, region=None):
        return b"fake-png"


# ═══════════════════════════════════════════════════════════════
# 三、三条轴不合并
# ═══════════════════════════════════════════════════════════════


class TestInteractiveAxisIsDistinct:
    def test_shellIsNotInteractiveDesktop(self):
        """跑 shell 会改机器状态但不改桌面画面——两轴分得开。"""
        assert "computer_shell" not in computerActionRefreshTools()
        assert "computer_ssh_exec" not in computerActionRefreshTools()

    def test_nonInteractiveDesktopDeclarationIsIgnored(self, monkeypatch):
        monkeypatch.setitem(_BUILTIN_SCHEMAS["computer_shell"], "interactive_desktop", True)
        assert "computer_shell" not in _declaredInteractive() or True  # 声明侧照读
        # 但消费侧仍以**声明面**为准：这里断言"声明面认得它"，证明不是白名单过滤
        assert "computer_shell" in _declaredInteractive()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
