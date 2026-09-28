# -*- coding: utf-8 -*-
"""G4 工具取消与超时处置：协作令牌 + 处置声明 + 进程收尸（红→绿）。

## 本片修的根因

超时一律转后台，且取消只到 asyncio 边界即止。两件事合起来让"已中止"成为假话：
进程型工具（`run_code` / `git` / `exec_command` / `computer_shell`）超时或用户
按下停止后，子进程照旧占 CPU、持文件锁、持续写盘，而界面与模型都以为它停了。

三个结构性缺口：

1. **`to_thread` 外部不可取消**——阻塞调用按规矩一律下沉线程池
   （`tool_executor._blocking_fetch` 立的规矩），而 `Task.cancel()` 对已进入
   `to_thread` 的调用只丢结果、不停执行。故取消必须**协作式下沉进 worker**：
   worker 自查令牌，或把进程杀灭动作注册成回调由外部触发。
2. **处置一刀切**——"转后台"对纯 IO 型工具是对的，对进程型工具是错的。
   缺的是"这个工具被放弃时意味着什么"这一声明维度。
3. **杀灭原语无人接线**——`exec_sandbox` 的进程组杀灭已存在且跨平台，
   但主工具路不经过它。

## 判据不许用假对象充数

进程是否真的没了，只能用**真实存活状态**回答。故本文件的进程用例一律真起
`subprocess.Popen`（自成一团，供进程组杀灭）并按 `poll()` 断言，不用 `MagicMock`
冒充——那测的是调用次数，不是取消效果。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

POSIX = sys.platform != "win32"


def _spawnSleep(seconds: float = 30.0) -> subprocess.Popen:
    """起一个真实长睡进程。POSIX 下自成一团——进程组杀灭的前提，也是安全前提：
    未成团的进程 `getpgid` 返回宿主进程组，杀它会连带杀掉宿主自身。"""
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        start_new_session=POSIX,
    )


async def _awaitReap(proc: subprocess.Popen) -> bool:
    """等**真事实**：OS 报出子进程已退出；返回是否在收尸窗口内等到。

    此前这里是「让步 200 次」的计数等待（`for _ in range(200)` + `sleep(0)`），
    想当然地认为"让出若干轮就够 OS 回收完子进程"。空载机上 1~7 次让步即命中，
    看着必然够用；而在 CI 上受保护子集与 4000+ 条用例共享同一批 vCPU，
    `sleep(0)` 只把控制权交回事件循环、**不保证内核完成一次调度**：

        构建 cnb-v4f-1k3jg3a81（PR #308）实测：
        FAILED TestCancelTokenProtocol::testCancelRunsRegisteredKillAction
        AssertionError: 令牌置位后进程仍然存活——回调没兑现

    复现口径：48 路 CPU 自旋超额订阅下跑本用例，200 次让步在 5ms 内走完而子进程
    仍未被回收（`poll()` 仍为 `None`），用例转红——**这是假红**：杀灭回调已兑现，
    只是等待窗口被机器负载决定（`AGENTS.md` 修复教义第 2 条点名的
    「判据与机器速度捆绑」形态）。

    故等待改为「等 OS 报出子进程退出」，上界取**单源常量** `KILL_GRACE_S`
    （生产侧 `_reapCancelled` / 沙箱路径收尸用的同一个窗口，不新造第二个尺度）：
    窗口内等到 ⇒ True；窗口外没等到 ⇒ False，判据照旧红——判据从"机器多快"
    回到"进程还在不在"。
    """
    from neurova.sandbox.exec_sandbox import KILL_GRACE_S

    try:
        await asyncio.to_thread(proc.wait, timeout=KILL_GRACE_S)
        return True
    except subprocess.TimeoutExpired:
        return False


def _reap(proc: subprocess.Popen) -> None:
    """兜底回收测试自己起的进程（用例失败时也不留残留）。

    等待上界同取 `KILL_GRACE_S`：与判据用的是同一个窗口，不给同一件事第二份定义。
    """
    from neurova.sandbox.exec_sandbox import KILL_GRACE_S

    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=KILL_GRACE_S)
    except Exception:  # noqa: BLE001 - 测试兜底不做判据
        pass


# ═══════════════════════════════════════════════════════════════
# 一：协作令牌协议
# ═══════════════════════════════════════════════════════════════


class TestCancelTokenProtocol:
    def testFreshTokenIsNotCancelled(self):
        from neurova.core.cancel_token import CancelToken

        assert CancelToken().cancelled() is False

    @pytest.mark.asyncio
    async def testCancelRunsRegisteredKillAction(self):
        """置位⇒回调执行，且**进程真的没了**（不看调用次数）。

        异步用例：收尸要落一次 OS 调度，轮询须让出事件循环才观察得到。
        """
        from neurova.core.cancel_token import CancelToken
        from neurova.sandbox.exec_sandbox import killProcessTree

        proc = _spawnSleep()
        try:
            assert proc.poll() is None
            token = CancelToken()
            token.onCancel(lambda: killProcessTree(proc))
            token.cancel("timeout")
            assert await _awaitReap(proc), (
                "令牌置位后进程仍然存活——回调没兑现"
            )
        finally:
            _reap(proc)

    def testActionRegisteredAfterCancelRunsImmediately(self):
        """置位后注册的回调必须**立即兑现**：竞态下注册的杀灭动作不许静默丢弃。"""
        from neurova.core.cancel_token import CancelToken

        ran = []
        token = CancelToken()
        token.cancel("user")
        token.onCancel(lambda: ran.append("late"))
        assert ran == ["late"], "置位后注册的回调被丢掉——竞态窗口里的进程会永远残留"

    def testSecondCancelDoesNotRerunActions(self):
        from neurova.core.cancel_token import CancelToken

        ran = []
        token = CancelToken()
        token.onCancel(lambda: ran.append(1))
        token.cancel()
        token.cancel()
        assert ran == [1]

    def testRaiseIfCancelledSurfacesCancelledError(self):
        from neurova.core.cancel_token import CancelToken

        token = CancelToken()
        token.raiseIfCancelled()  # 未置位不抛
        token.cancel("user")
        with pytest.raises(asyncio.CancelledError):
            token.raiseIfCancelled()

    def testBrokenActionDoesNotBlockRemainingActions(self):
        """一个杀灭回调失败不得连带阻断其余回调——否则一个坏工具的进程会拖住全部收尸。"""
        from neurova.core.cancel_token import CancelToken

        ran = []

        def boom():
            raise RuntimeError("kill failed")

        token = CancelToken()
        token.onCancel(boom)
        token.onCancel(lambda: ran.append("second"))
        token.cancel()
        assert ran == ["second"]


# ═══════════════════════════════════════════════════════════════
# 二：超时处置声明（复用 G3 的能力声明位，不另开声明文件）
# ═══════════════════════════════════════════════════════════════


class TestTimeoutDispositionDeclaration:
    def testUndeclaredIsBackground(self):
        """三态默认 BACKGROUND ⇒ 不声明即与改造前逐字节同行为。"""
        from neurova.core.tool_capability import TimeoutDisposition, ToolCapability

        assert ToolCapability().timeoutDisposition is TimeoutDisposition.BACKGROUND

    def testDeclaredKillParsed(self):
        from neurova.core.tool_capability import TimeoutDisposition, parseToolCapability

        cap = parseToolCapability({
            "readOnly": False, "concurrentSafe": False,
            "writeScopes": ["shared"], "timeoutDisposition": "kill",
        })
        assert cap is not None and cap.timeoutDisposition is TimeoutDisposition.KILL

    def testUnknownDispositionVoidsWholeDeclaration(self):
        """形态非法不部分采信：半个声明比没声明更危险（同 G3 既有拒收规则）。"""
        from neurova.core.tool_capability import parseToolCapability

        assert parseToolCapability({
            "readOnly": False, "concurrentSafe": False,
            "writeScopes": ["shared"], "timeoutDisposition": "nuke",
        }) is None

    def testProcessToolsDeclaredKill(self):
        """四类进程型工具声明 KILL；`exec_command` 另经会话回收，仍须声明。"""
        from neurova.agent.tool_coordinator import resolveTimeoutDisposition
        from neurova.core.tool_capability import TimeoutDisposition

        for name in ("run_code", "git", "exec_command", "computer_shell"):
            assert resolveTimeoutDisposition(name) is TimeoutDisposition.KILL, name

    def testNonProcessToolStaysBackground(self):
        """反向控制：非进程型工具不许被顺手改成 KILL（那是无差别杀灭）。"""
        from neurova.agent.tool_coordinator import resolveTimeoutDisposition
        from neurova.core.tool_capability import TimeoutDisposition

        for name in ("web_search", "memory_search", "file_parse", "calculator"):
            assert resolveTimeoutDisposition(name) is TimeoutDisposition.BACKGROUND, name


# ═══════════════════════════════════════════════════════════════
# 三：处置分派（真进程）
# ═══════════════════════════════════════════════════════════════


class TestTimeoutDispositionDispatch:
    @pytest.mark.asyncio
    async def testKillDispositionReapsProcessWithinGrace(self):
        """KILL：超时后进程真的没了，且返回 cancelled 形态（不留僵尸、不谎报）。"""
        from neurova.agent.tool_coordinator import ToolCoordinator
        from neurova.core.cancel_token import CancelToken
        from neurova.core.tool_capability import TimeoutDisposition
        from neurova.sandbox.exec_sandbox import killProcessTree

        proc = _spawnSleep()
        coordinator = ToolCoordinator()
        token = CancelToken()
        try:
            async def slow():
                token.onCancel(lambda: killProcessTree(proc))
                await asyncio.sleep(30)
                return {"late": True}

            outcome = await coordinator.run_with_timeout(
                "run_code", slow, timeout=0.2,
                token=token, disposition=TimeoutDisposition.KILL,
            )

            assert outcome["status"] == "cancelled"
            assert outcome["cancelled"] is True
            assert outcome["reason"] == "timeout"
            assert "run_code" == outcome["tool_name"]
            # 宽限期"有界"是**结构事实**，不是秒数事实：收尸走单源常量
            # `KILL_GRACE_S`（有限的正数），故不存在无限等待的路径。
            # 这里断言那个常量本身的形态，不量任何耗时（量耗时会绑上机器负载）。
            from neurova.sandbox.exec_sandbox import KILL_GRACE_S

            assert 0 < KILL_GRACE_S < float("inf"), (
                f"收尸窗口常量 {KILL_GRACE_S!r} 不是有界正数——KILL 分支可能无限等待"
            )
            assert await _awaitReap(proc), (
                "KILL 分支返回了，但进程还在跑"
            )
        finally:
            _reap(proc)

    @pytest.mark.asyncio
    async def testAbortDispositionCancelsTaskWithoutBackground(self):
        """ABORT：可打断的 async 工具超时即取消，不走转后台（也不留悬挂任务）。"""
        from neurova.agent.tool_coordinator import ToolCoordinator
        from neurova.core.tool_capability import TimeoutDisposition

        coordinator = ToolCoordinator()
        reached = []

        async def slow():
            await asyncio.sleep(30)
            reached.append(True)
            return {"late": True}

        outcome = await coordinator.run_with_timeout(
            "web_search", slow, timeout=0.2, disposition=TimeoutDisposition.ABORT,
        )
        assert outcome["status"] == "cancelled"
        assert outcome["cancelled"] is True
        await asyncio.sleep(0.05)
        assert reached == [], "ABORT 分支下被放弃的任务仍在跑"

    @pytest.mark.asyncio
    async def testUndeclaredToolStillGoesBackground(self):
        """等价性守卫：未声明工具的超时行为与改造前逐字节一致（保守默认不许漂移）。"""
        from neurova.agent.tool_coordinator import ToolCoordinator

        coordinator = ToolCoordinator()
        finished = asyncio.Event()

        async def slow():
            await asyncio.sleep(0.3)
            finished.set()
            return {"late": True}

        outcome = await coordinator.run_with_timeout("web_search", slow, timeout=0.05)
        assert outcome["status"] == "background"
        assert "task_id" in outcome
        assert outcome.get("cancelled") is None
        await asyncio.wait_for(finished.wait(), timeout=3)

    @pytest.mark.asyncio
    async def testKillDispositionWithoutTokenStillReaps(self):
        """令牌缺席（如后台续跑）时 KILL 仍须取消任务——只是没有回调可触发。"""
        from neurova.agent.tool_coordinator import ToolCoordinator
        from neurova.core.tool_capability import TimeoutDisposition

        coordinator = ToolCoordinator()
        reached = []

        async def slow():
            await asyncio.sleep(30)
            reached.append(True)

        outcome = await coordinator.run_with_timeout(
            "git", slow, timeout=0.2, disposition=TimeoutDisposition.KILL,
        )
        assert outcome["cancelled"] is True
        await asyncio.sleep(0.05)
        assert reached == []


# ═══════════════════════════════════════════════════════════════
# 四：取消的统计身份（裁决不是故障）
# ═══════════════════════════════════════════════════════════════


class TestCancellationCountsAsDecision:
    def testCancelledEnvelopeIsPolicyDenial(self):
        from neurova.security.governance import is_policy_denial

        assert is_policy_denial({"cancelled": True, "status": "cancelled"}) is True

    def testRealFailureIsStillNotADecision(self):
        """反向控制：真故障不许被顺手划进裁决（那是把失败洗成决策）。"""
        from neurova.security.governance import is_policy_denial

        assert is_policy_denial({"success": False, "error": "磁盘满"}) is False

    def testCancelledToolDoesNotStickAsFailureInEvidence(self):
        """用户按几次停止，不得把一个好工具在治理面上永久钉死（MIN(success) 粘性）。"""
        from neurova.security.governance import is_policy_denial
        from neurova.skills import creation_governance as governance

        assert is_policy_denial({"cancelled": True}) is True
        governance.begin_task()
        governance.record_tool_execution(
            "run_code", {"code": "x"}, False,
            {"cancelled": True, "status": "cancelled", "tool_name": "run_code"},
        )
        task = governance._execution.get()
        assert task["success"] is True, (
            "取消被记成了工具失败——粘性 MIN(success) 会把该结构身份永久判失败"
        )
        assert [step["tool"] for step in task["steps"]] == ["run_code"], (
            "裁决事件仍须留步（结构身份的输入），只是不承担成败"
        )

    def testRealFailureStillSticks(self):
        """反向控制：真失败照旧粘住（收窄不得把失败一并放过）。"""
        from neurova.skills import creation_governance as governance

        governance.begin_task()
        governance.record_tool_execution(
            "run_code", {"code": "x"}, False, {"success": False, "error": "退出码 1"},
        )
        assert governance._execution.get()["success"] is False


# ═══════════════════════════════════════════════════════════════
# 五：取消的反馈环（终态必须回到下一轮）
# ═══════════════════════════════════════════════════════════════


class TestCancelledBackgroundFeedback:
    @pytest.mark.asyncio
    async def testCancelledBackgroundToolEmitsHint(self):
        """已转后台的工具被取消后不许凭空消失——终态必须可被下一轮取走。"""
        from neurova.agent.tool_coordinator import ToolCoordinator

        coordinator = ToolCoordinator()

        async def slow():
            await asyncio.sleep(30)

        envelope = await coordinator.run_with_timeout("web_fetch", slow, timeout=0.05)
        assert envelope["status"] == "background"
        task_id = envelope["task_id"]

        entry = coordinator._background[task_id]
        entry["task"].cancel()
        for _ in range(60):
            hints = [h for h in coordinator._pending_hints if h.get("task_id") == task_id]
            if hints:
                break
            await asyncio.sleep(0.05)
        hints = [h for h in coordinator._pending_hints if h.get("task_id") == task_id]
        assert hints, "被取消的后台工具没有投递终态——写入→读取→反馈的第三环断裂"
        assert hints[0].get("cancelled") is True
        assert hints[0]["success"] is False


# ═══════════════════════════════════════════════════════════════
# 六：单一事实源（防第二条杀灭路诞生）
# ═══════════════════════════════════════════════════════════════


class TestKillPrimitiveIsSingleSource:
    def testProcessGroupKillHasOneSite(self):
        """全仓只有一处 `killpg`：进程组杀灭不许有第二份实现。"""
        from tests import ast_scan

        offenders = []
        for ref in ast_scan.sourceRefsUnder(ast_scan.PRODUCTION_ROOT, hints=("killpg",)):
            for lineno, line in enumerate(ref.code.splitlines(), start=1):
                if "killpg" in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{ref.path}:{lineno}")
        assert len(offenders) == 1, (
            "进程组杀灭出现了第二处实现（应全部经 exec_sandbox.killProcessTree）：\n  "
            + "\n  ".join(offenders)
        )

    def testKillProcessTreeIsPublicSingleEntry(self):
        """杀灭原语的公开入口只有一个名字，旧私有名的调用方全部收口到它。"""
        from tests import ast_scan

        from neurova.sandbox.exec_sandbox import killProcessTree

        assert callable(killProcessTree)
        second = []
        for ref in ast_scan.sourceRefsUnder(ast_scan.PRODUCTION_ROOT, hints=("_killTree",)):
            for lineno, line in enumerate(ref.code.splitlines(), start=1):
                if "_killTree" in line and not line.lstrip().startswith("#"):
                    second.append(f"{ref.path}:{lineno}")
        assert not second, "旧杀灭名仍在生产侧存活（第二份实现）：\n  " + "\n  ".join(second)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
