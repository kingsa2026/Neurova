# -*- coding: utf-8 -*-
"""上一格用例置位的轮级取消令牌，不得漏到下一格。

## 这份守卫在挡什么

`tests/unit/execution/test_executionLayersTransportHalfRetired.py` 的交付锁
`test_runtimeHalfStillProducesAWorkingLocalRuntime` 断言"本地运行时真 exec 得回来"。
它在 CI 单腿里两次被判红（`cnb-h41-1k5nnd37s#003`、`cnb-7o4-1k5nkg9f3#003`，
7823 条里唯一一条红），单文件单跑却必绿：

    FAILED ...::test_runtimeHalfStillProducesAWorkingLocalRuntime
    AssertionError: 本地运行时执行不回来：
      ExecutionResult(success=False, exit_code=-9)

`exit_code=-9` 是 SIGKILL 的读数。`LocalExecutor.exec` 起完进程就把杀灭动作注册给
**本轮令牌**，而 `CancelToken.onCancel` 对"已置位"的令牌当场兑现——进程在
`communicate` 之前就死了。信使不是那条交付锁，是上一格用例留下的置位。

## 根因：夹具只关了一头

`tests/conftest.py` 的 `_reset_turn_cancel_token` 原先只在用例**入口**置 None。
取消语义的用例（`tests/unit/tools/test_tool_cancellation.py` 的协作令牌族）是在
协程里置位的：`ContextVar.set` 只改当前 context，而 pytest 调用每条用例时沿用
上一条用例的 context。实测（同一用例内，worker 置位后当场真起一条 `exec`）：

    exec under cancelled token -> False -9

于是"下一格从干净的 None 开始"这句只在前置那句被真正执行时成立——它在用例收尾
**之后**，而收尾读到的已经是置位令牌。两头都置才关得掉这条通道。

## 本档钉两件事（都要求真进程，不用 MagicMock 冒充）

1. **越界面是真起进程**：置位令牌在场时，`LocalExecutor.exec` 必须真拿到 `-9`——
   否则第 2 条的前提不成立，先查那条链。
2. **隔离在两头**：上一格置位过，本格起进程照样得回来。

反向控制：删掉夹具尾部那句 `setTurnCancelToken(None)` 并跑「协作令牌族 + 本档」
两文件，第 2 条即红（`-9`）。
"""
from __future__ import annotations

import asyncio
import sys

from neurova.core import cancel_token
from neurova.execution_layers import LocalExecutor


def _hasKillAction(token) -> bool:
    """这一轮令牌上有没有已注册的杀灭回调（`exec` 起完进程就会挂上）。"""
    return bool(getattr(token, "_actions", None))


def _execOnce():
    """真起一条进程，返回执行读数（不用替身：`-9` 只有真进程读得出）。"""
    return asyncio.run(LocalExecutor().exec(
        command=sys.executable, args=["-c", "print(1)"], timeout=30))


def test_cancelledTokenReallyKillsTheProcess():
    """前提自证：**这一发进程启动之后**发生的取消，真把进程杀掉（`-9`，不是假红）。

    为什么不能"先置位再起进程"：`registerKillAction` 收 `launchedAtEpoch`（起进程那一刻的
    置位次数），回调只为**这一发进程启动之后**的取消兑现。起进程之前就置位时，epoch 与之
    相等 ⇒ 那条回调不兑现——这正是"用户点一次停止，取消顺着整轮后续命令一路传染"要挡的
    那一半（实测：第一发 `print(1)` 成功、本轮 `cancel("user")` 之后下一发立即 `-9`，
    而它连一行都没跑）。所以本格把置位挪到进程**已经在跑**之后：请求发出 → 置位 → 拿读数。
    """
    token = cancel_token.CancelToken()
    cancel_token.setTurnCancelToken(token)
    try:
        async def _execThenCancel():
            task = asyncio.ensure_future(LocalExecutor().exec(
                command=sys.executable, args=["-c", "import time; time.sleep(30)"], timeout=30))
            # 等进程真起来并注册好回调：`exec` 的第一步就是把句柄交给令牌。
            for _ in range(600):
                await asyncio.sleep(0.01)
                if token.cancelEpoch or _hasKillAction(token):
                    break
            token.cancel("user")
            return await task

        result = asyncio.run(_execThenCancel())
    finally:
        cancel_token.setTurnCancelToken(None)
    expected_code = 1 if sys.platform == "win32" else -9  # win32 走 taskkill /T /F（TerminateProcess 退出码 1），POSIX 才是 SIGKILL
    assert (result.success, result.exit_code) == (False, expected_code), (
        f"进程在跑之后置位令牌，进程却没被杀掉（{result}）——本档第 2 条的前提不成立，先查那条链")


def test_cancelledTokenFromPreviousCaseDoesNotReachThisOne():
    """隔离判据：上一格置位过令牌，本格起进程照样得回来。"""
    leaked = cancel_token.getTurnCancelToken()
    assert leaked is None, (
        "上一格置位的轮级令牌漏到了本格——`tests/conftest.py` 的 "
        "`_reset_turn_cancel_token` 必须在用例入口与出口**各**置 None；"
        "只关入口时收尾读到的已是置位令牌，下一条起进程的用例拿到 -9")

    result = _execOnce()
    assert result.success and "1" in (result.stdout or ""), (
        f"本地运行时执行不回来：{result}")
