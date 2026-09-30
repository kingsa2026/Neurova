# -*- coding: utf-8 -*-
"""T-02 · 桌面/浏览器工具的三面一致性守卫（纯守卫，零生产行为变更）。

## 要拦的东西

同一族电脑操控工具的名字，在三处并行登记：

| 面 | 落点 | 谁读它 |
|----|------|--------|
| 治理面 | `tool_executor.COMPUTER_USE_TOOLS` | `normalize_computer_params` 准入（`:1982`）、审计（`:1995`）、事件补拍（`:4869`） |
| 参数面 | `tool_executor._COMPUTER_TOOL_PARAM_KEYS` | `normalize_computer_params` 的未知键拒绝 |
| 派生面 | `tool_executor._builtin_dispatch` | 工具名 → 执行方法 |

三表各自手写、互不对账。既有守卫只覆盖一条轴
（`test_action_refresh_declaration.py:129`：`interactive_desktop` 派生名 ⊆ 治理面），
**"漏填其中一表"这一类漂移没有任何代价**：名字进了派生面却没进参数面 ⇒ 参数校验整层被跳过；
进了治理面却没进派生面 ⇒ 走"未知工具"回落。

## 现状实测（2026-09-30，基线 `008a3e2a`）

治理面 20 项、参数面 20 项，**逐名一致**；20 项全部在派生面内 ⇒ 前三条判据当前为绿。
唯一分叉是 **`browser_read`**：它有 schema、在派生面，却**不在治理面**。

这不是漏填，而是**一次真实的设计缺口被本守卫逮住**：`browser_read` 走 web_reach 通路、
不触碰 BrowserManager，因此把它塞进 `COMPUTER_USE_TOOLS` 会错误地给它套上
`normalize_computer_params` 与桌面审计；但它当前又确实绕过了本域的全部参数准入。
**处置需人裁决（属"改哪一面"的产品判断），故本守卫把它登记为显式例外而非静默放过**——
例外名单是唯一事实源：任何**新增**分叉即红，把 `browser_read` 从名单里销掉也要求同步改代码。

## 与三条既有轴的关系（不合并）

`capability.writeScopes` 问"并发会不会互踩"、`arbitrary_command` 问"会不会执行任意命令"、
`interactive_desktop` 问"动作会不会改变共享桌面画面"（见 `test_action_refresh_declaration.py`
的同名论述）。本文件**不新造第四轴**，只断言三张名字表描述的是同一批工具。
"""

from __future__ import annotations

from neurova.agent.tool_coordinator import resolveToolCapability
from neurova.tool_executor import (
    _COMPUTER_TOOL_PARAM_KEYS,
    COMPUTER_USE_TOOLS,
    ToolExecutor,
)

# 派生面是**类属性**（`tool_executor.py:269`，不在 __init__ 内）⇒ 无须实例化即可读，
# 避免为了拿一张表去构造 ToolExecutor（那会绕开真实装配点并引入 agent 身份依赖）。
_builtin_dispatch = ToolExecutor._builtin_dispatch

# 已知并已被记录的分叉：派生面有、治理面无。**加名字必须带理由，删名字必须同步改代码。**
KNOWN_SURFACE_DIVERGENCES: dict[str, str] = {
    "browser_read": (
        "web_reach 通路，不经 BrowserManager；入治理面会被错误施加桌面参数准入与审计。"
        "待裁决：是补一条 browser_ 侧参数面，还是并入治理面（见工单集 T-02 附注）。"
    ),
}


def _desktopBrowserDispatchedNames() -> set:
    """派生面里所有电脑操控工具名（按前缀取，不另立名单）。"""
    return {n for n in _builtin_dispatch if n.startswith("computer_") or n.startswith("browser_")}


def _surfaceDivergences(surface: set, dispatched: set) -> set:
    """纯函数：派生面有、治理面无的名字集合。

    做成纯函数是为了让"反向控制"能喂假数据验证它真的会报东西——
    判据若整体失效，第一节会空转通过（沿用上下文域台账守卫的同一条纪律）。
    """
    return dispatched - surface


def test_computerUseToolsAllHaveParamKeys():
    """在治理面上的工具，必须有参数白名单——否则未知键被无声放行。"""
    missing = sorted(COMPUTER_USE_TOOLS - set(_COMPUTER_TOOL_PARAM_KEYS))
    assert not missing, f"治理面有、参数面无（漏填白名单 ⇒ 参数校验整层跳过）: {missing}"


def test_computerUseToolsAllDispatchable():
    """治理面上的工具必须能派生——否则声明了却走"未知工具"回落。"""
    missing = sorted(COMPUTER_USE_TOOLS - set(_builtin_dispatch))
    assert not missing, f"治理面有、派生面无（不可执行）: {missing}"


def test_paramKeysNotOrphanedFromSurface():
    """反向：参数白名单里的名字必须也在治理面，否则白名单是第二份孤儿定义。"""
    orphans = sorted(set(_COMPUTER_TOOL_PARAM_KEYS) - COMPUTER_USE_TOOLS)
    assert not orphans, f"只在参数面出现（孤儿定义）: {orphans}"


def test_surfaceToolsAllDeclareCapability():
    """治理面每个工具须有并行能力声明，判据取生产唯一解析入口，不在测试里二次解析 schema。"""
    undeclared = [n for n in sorted(COMPUTER_USE_TOOLS) if resolveToolCapability(n) is None]
    assert not undeclared, (
        f"未声明能力 ⇒ 并发调度按串行处置且无从审计依据: {undeclared}"
    )


def test_dispatchedDesktopBrowserNamesAreReconciledOrWhitelisted():
    """派生面的电脑操控名字，要么在治理面，要么在显式例外名单——新分叉即红。"""
    diverging = _surfaceDivergences(set(COMPUTER_USE_TOOLS), _desktopBrowserDispatchedNames())
    unexpected = sorted(diverging - set(KNOWN_SURFACE_DIVERGENCES))
    assert not unexpected, (
        f"派生面有、治理面无且未登记例外: {unexpected}\n"
        f"要么补进 COMPUTER_USE_TOOLS，要么在 KNOWN_SURFACE_DIVERGENCES 写明理由"
    )
    # 例外名单也不许变成"僵尸登记"：名单里的名字若已并入治理面，就该从名单删掉
    stale = sorted(set(KNOWN_SURFACE_DIVERGENCES) - diverging)
    assert not stale, f"例外名单里有过期登记（已收口却仍占位）: {stale}"


def test_guardIsNotVacuous():
    """反向控制：喂一份刻意分叉的数据，判据必须报出差异——否则上面几条在空转。"""
    assert _surfaceDivergences({"computer_click"}, {"computer_click", "browser_read"}) == {"browser_read"}, (
        "差异计算本身失效：真实分叉存在却算不出来"
    )
    # 并且当前代码里确实有一处被登记的分叉（若将来全部收口，本断言会红，提醒同步删例外名单）
    assert _desktopBrowserDispatchedNames() - set(COMPUTER_USE_TOOLS) == set(KNOWN_SURFACE_DIVERGENCES), (
        "实际分叉集合与例外名单不再相等——更新 KNOWN_SURFACE_DIVERGENCES 或修复收口"
    )
