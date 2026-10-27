# -*- coding: utf-8 -*-
"""本地执行体必须在自己收完尸之后把取消挂钩摘掉（§6-404 形态，本批实测）。

病灶（不是"测试写得不好"）：`LocalExecutor.exec` 每起一个命令就往**本轮**取消令牌上
注册一条杀灭回调，却从不撤回。令牌按轮持有、回调按进程注册——两个生命周期不同，
于是本轮**后续任何一次取消**都会去杀一个早已结束的 pid：

    第一发 `print(1)`（success=True，令牌残留回调 1 条）
    → 本轮 `token.cancel("user")`
    → 下一发 `print(2)` 立即 `exit_code=-9`

第二发并非"被取消"：它 `Popen` 出来之后注册自己的回调时，令牌**已置位**，注册口按
"迟到的回调立即兑现"（那条规则本身是对的，它救的是竞态窗口里的进程）当场把它杀了。
pid 还会被系统复用，届时杀的是别人的进程。

本档两格，都是行为判据，不认实现形状：
1. 正常执行完之后令牌上**零残留**；
2. 本轮取消之后新起的命令照常跑完（残留回调不许把新进程带走）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def turnToken():
    """绑一只本轮令牌，用完清掉（不跨用例留全局状态）。"""
    from neurova.core.cancel_token import CancelToken, setTurnCancelToken

    token = CancelToken()
    setTurnCancelToken(token)
    try:
        yield token
    finally:
        setTurnCancelToken(None)


def _run(command: str) -> "object":
    from neurova.execution_layers import LocalExecutor

    return asyncio.run(LocalExecutor().exec(command=sys.executable, args=["-c", command], timeout=30))


def testKillHookIsHungUpAfterTheProcessIsReaped(turnToken):
    result = _run("print(1)")

    assert result.success, f"本地运行时执行不回来：{result}"
    assert turnToken._actions == [], (
        "命令结束后取消令牌上还挂着杀灭回调：本轮后续的每一次取消都会去杀一个已经结束的 pid"
        "（pid 被复用时杀的是别人的进程）")


def testCancelDoesNotFollowIntoCommandsStartedAfterwards(turnToken):
    assert _run("print(1)").success, "前提不成立：第一发就没跑成"

    turnToken.cancel("user")     # 用户停止：只该影响**当时在跑**的那些命令

    later = _run("print(2)")
    assert later.success and "2" in (later.stdout or ""), (
        f"取消之后新起的命令被立刻杀掉（exit={later.exit_code}）："
        "上一发残留的杀灭回调在新进程注册时被立即兑现")
