# -*- coding: utf-8 -*-
"""Computer Use 工具面集成判据（原为零断言的 print 脚本，按工单集 §19 D-7 ⑤ 改写）。

## 为什么必须改写而不是"修绿"

原形态是一份 `async def` 却未标 `pytest.mark.asyncio` 的 print 脚本：在
`asyncio: mode=Mode.STRICT` 下直接判红，而在 `__main__` 下手动跑时——

它的第 1 步调 `get_computer_use_manager().get_status()`，而这个方法**在生产里不存在**
（facade 的读侧叫 `doctor_report()`）。异常被 `except` 打印成一行"✗ 初始化失败"后
`return`，于是第 2–6 步（Agent 初始化、schema 检查、工具列表、ToolRouter、真点击/真键入）
**一次都没有执行过**。一份看起来在覆盖六件事的脚本，实际守卫数为零。

更要紧的是第 6 步：它真调 `computer_click`/`computer_type`——一个常驻测试会移动真实
光标、往真实焦点窗口打字。这种形状绝不能进 CI 被测集，所以本轮把它改成**无副作用**的
契约判据。

## 今天真正守得住的三件事

1. 能力自检的读侧形状（`doctor_report`，含 T-07 落地的三态 `capabilities`）；
2. 工具清单确实注册着（原脚本"逐个查 schema"的意图，落在生产单源上）；
3. 退役面不得回潮——原脚本的候选清单里还写着 `computer_visual_parse`（D-5 已整条退役），
   把它从"期望它存在"倒过来钉成"期望它不存在"，这条才第一次具备拦截力。
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from neurova.computer_use import ComputerUseManager, get_computer_use_manager

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_doctorReportIsTheRealReadSideAndCarriesTheTriState():
    """facade 的读侧是 `doctor_report()`；能力面必须带 T-07 的三态读数。

    断言键集合而不是"有没有某个键"：少一个键就意味着某个自检项静默消失。
    """
    report = get_computer_use_manager().doctor_report()

    assert {"pillow", "pyautogui_input", "uia", "dpi_aware", "screen_metadata"} <= set(report), \
        sorted(report)
    for axis in ("screenshot", "input", "uia", "aria", "camofox", "vision"):
        assert axis in report["capabilities"], f"能力面少了 {axis} 轴：{sorted(report['capabilities'])}"
        assert {"state", "owner", "reason"} <= set(report["capabilities"][axis])


def test_computerUseToolsAreAllRegisteredWithDescriptions():
    """原脚本第 3 步的意图：工具名逐个能在 schema 里查到且 description 非空。

    清单只放**模型可见工具**。`smart-click`/`smart-type` 不在此列——它们是 HTTP 端点
    （前端语义按钮），模型面走 `browser_*`/`computer_*`；退役的 `computer_visual_parse`
    由下一条反向锁单独看住。
    """
    from neurova.builtin_tools import _BUILTIN_SCHEMAS

    expected = {
        "computer_screenshot", "computer_click", "computer_type", "computer_scroll",
        "computer_shell", "computer_dom_snapshot", "computer_som_snapshot",
        "browser_dom_snapshot", "browser_click_ref", "browser_fill_ref",
    }
    missing = sorted(name for name in expected if name not in _BUILTIN_SCHEMAS)
    assert not missing, f"这些工具从注册面上消失了：{missing}"
    for name in expected:
        assert (str(_BUILTIN_SCHEMAS[name].get("description") or "")).strip(), \
            f"{name} 的 description 为空——模型看到的就只剩一个名字"

    # 语义点击/输入只有 HTTP 面：schema 里出现它们却没有对应执行体，就是幻影工具
    for httpOnly in ("smart_click", "smart_type"):
        assert httpOnly not in _BUILTIN_SCHEMAS, \
            f"{httpOnly} 进了模型可见面，但 dispatch 里没有它的执行体"


def test_retiredVisualParseCannotComeBack():
    """D-5 已整条退役 `visual-parse`（端点/模型/前端封装/按钮/locale 同批撤）。

    原脚本把它当"应当存在的工具"列在清单里，那是一条会误导人的期望；这里倒过来
    钉成反向锁。扫描必须排除工具自己的会话备份快照目录，否则 67 个 `.source`
    备份文件会造成假命中（本轮实测踩过）。
    """
    hits = subprocess.run(
        ["git", "-c", "core.quotepath=false", "grep", "-lE",
         "visual_parse|visualParse|VisualParse", "--", "neurova", "NeurUI/src"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert hits.returncode in (0, 1), hits.stderr
    real = [line for line in (hits.stdout or "").splitlines()
            if line.strip() and ".mimosa" not in line]
    assert not real, f"退役面回潮到生产码/前端源码：{real}"


def test_facadeExposesNoPhantomGetStatus():
    """反向锁：读侧只有一个名字。`get_status` 是这份旧脚本虚构出来的门面。

    它不是"少个方法"那么无害——两条读同一件事的路径会给出两种形状，
    而 13 例常驻红里有几例正是照着那条不存在的路径写的。
    """
    assert not hasattr(ComputerUseManager, "get_status"), (
        "facade 上又长出第二个状态读侧——BrowserManager.get_status 与 "
        "ComputerUseManager.doctor_report 已各自是单源，这里再加就是第三份"
    )
