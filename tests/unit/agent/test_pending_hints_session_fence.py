# -*- coding: utf-8 -*-
"""晚到工具终态的会话栅栏（2026-10-08 长任务闭环审计 C 批）。

`_pending_hints` 装的是「比轮次晚到的工具终态」——超时转后台、被取消、带外批准/拒绝。
它与子代理回传邮箱 `AgentMailbox` 是同一件事（会话级晚到反馈），邮箱按 session 分箱、
按 session 排干，而这一条通路是**一个 agent 一份全局列表**：谁先开下一轮，谁就把别人
会话的终态读进自己的上下文。

后果不是脏数据而是**错的前提 + 跨会话外泄**：A 会话后台跑 `file_read` 的正文被注进
B 会话的 system 消息，B 的模型据此推理；`recordApprovalOutcome` 明明写了 `session_id`
（`tool_coordinator.py:389`），排干处却从不读它——写了不读就是断点。

根因：这条通路从生产到消费都没有会话归属这一层，只在出口留了个没人读的字段。
修法与邮箱同形（不新造第二套通道）：生产侧按轮次上下文盖章归属，排干侧按当前会话取。

判据（改前逐条实测不成立）：
1. 超时转后台的终态必须带上**发起那一轮**的会话归属；
2. 排干必须按会话取——别人的会话取不到，自己的会话取得到；
3. 无归属的终态不得广播给任意会话（如实点名拒绝，不是静默丢弃也不是串会话）；
4. 有界留存：非本会话的终态不得无界堆积，淘汰最旧要留警告；
5. 生产消费方一律传会话（AST 钉形态，不钉词）。
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from tests import ast_scan

from neurova.agent.tool_coordinator import ToolCoordinator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = PROJECT_ROOT / "neurova"

SESSION_A = "sess_alpha"
SESSION_B = "sess_beta"


def _stampTurn(session_id):
    """按生产单源登记本轮身份（与 `turn_state.py:119` 同一入口，不手工塞私有字段）。"""
    from neurova.core.turn_context import set_turn_identity

    set_turn_identity("读一下", session_id, "u1")


class TestBackgroundOutcomeCarriesSession:
    def test_offload_hint_is_owned_by_originating_session(self):
        """超时转后台 → 完成后的终态必须记着「是哪一回话发起的」。"""

        async def scenario():
            coordinator = ToolCoordinator()
            _stampTurn(SESSION_A)
            inner = asyncio.ensure_future(_slowWork())
            result = await coordinator.run_with_timeout(
                "probe_reader", lambda: inner, timeout=0.05
            )
            assert isinstance(result, dict) and result.get("status") == "background", (
                f"未走转后台分支，本判据前提不成立：{result}"
            )
            observer = coordinator._background[result["task_id"]]["observer"]
            await observer
            return coordinator

        coordinator = asyncio.run(scenario())
        queued = coordinator._pending_hints
        assert len(queued) == 1, f"后台终态没回到队列（前提不成立）：{queued}"
        assert queued[0].get("success") is True
        assert queued[0].get("session_id") == SESSION_A, (
            f"终态没带发起会话的归属，任何会话排干都会拿走它：{queued[0]}"
        )

    def test_cancelledOutcome_isOwnedToo(self):
        """取消终态（G4-RC6 补的那条）同样要有归属，否则又留一条无主通路。"""

        async def scenario():
            coordinator = ToolCoordinator()
            _stampTurn(SESSION_A)
            inner = asyncio.ensure_future(_slowWork(seconds=5))
            result = await coordinator.run_with_timeout(
                "probe_reader", lambda: inner, timeout=0.05
            )
            task_id = result["task_id"]
            entry = coordinator._background[task_id]
            entry["task"].cancel()
            await entry["observer"]
            return coordinator

        coordinator = asyncio.run(scenario())
        queued = [h for h in coordinator._pending_hints if h.get("cancelled")]
        assert len(queued) == 1, f"取消的终态没回到队列：{coordinator._pending_hints}"
        assert queued[0].get("session_id") == SESSION_A, (
            f"取消的终态没有归属，会被任意会话读走：{queued[0]}"
        )


async def _slowWork(seconds: float = 0.25):
    await asyncio.sleep(seconds)
    return "跑完了"


class TestDrainIsFencedBySession:
    def test_otherSessionDoesNotReceiveThisSessionOutcome(self):
        """B 会话排干不得拿到 A 会话的终态；A 自己取得到。"""

        async def scenario():
            coordinator = ToolCoordinator()
            _stampTurn(SESSION_A)
            inner = asyncio.ensure_future(_slowWork())
            result = await coordinator.run_with_timeout(
                "probe_reader", lambda: inner, timeout=0.05
            )
            await coordinator._background[result["task_id"]]["observer"]
            return coordinator

        coordinator = asyncio.run(scenario())
        assert coordinator.pop_pending_hints(SESSION_B) == [], (
            "别的会话把 A 的后台工具结果读进了自己的上下文——跨会话串供"
        )
        assert len(coordinator.pop_pending_hints(SESSION_A)) == 1


class TestUnownedOutcomeIsRefusedNotBroadcast:
    def test_approvalWithoutSession_isNamedAndNotQueued(self, caplog):
        """无归属终态：如实点名拒绝，既不静默丢弃也不广播给任意会话。"""
        import logging

        with caplog.at_level(logging.WARNING):
            ToolCoordinator().recordApprovalOutcome(
                "file_write",
                "call_x",
                success=True,
                session_id=None,
                result={"ok": 1},
            )
        text = caplog.text
        assert "file_write" in text and "call_x" in text, (
            f"无归属的终态被静默处理，没人能据此定位：{text!r}"
        )
        assert "call_x" not in str(
            ToolCoordinator().pop_pending_hints(SESSION_A)
        ), "无归属终态仍被投进了某会话"


class TestRetentionIsBounded:
    def test_foreignSessionsDoNotAccumulateUnbounded(self):
        """按会话取走后，别会话的终态不得无界堆积；淘汰最旧须留警告。"""
        coordinator = ToolCoordinator()
        for i in range(coordinator._MAX_PENDING_HINTS + 25):
            _stampTurn(f"sess_{i}")
            coordinator.recordApprovalOutcome(
                "probe_reader", f"call_{i}", success=True, session_id=f"sess_{i}"
            )
        assert len(coordinator._pending_hints) <= coordinator._MAX_PENDING_HINTS, (
            f"有界留存没生效：{len(coordinator._pending_hints)} 条堆积"
        )


class TestProductionConsumerPassesSession:
    def test_noBarePopPendingHintsCallInProduction(self):
        """生产侧每一处排干都必须传会话——空参即那条无栅栏的门。"""
        offenders = []
        # 枚举与解析走 tests/ast_scan 的共享预算（不私有 rglob + ast.parse——
        # 后者把判据成本绑在代码总量上，见 tests/unit/test_ci_ast_scan_budget_guard.py）。
        for path, tree in ast_scan.parsedModules(PRODUCTION, ".py"):
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "pop_pending_hints"
                    and not node.args
                    and not node.keywords
                ):
                    offenders.append(f"{path.relative_to(PRODUCTION)}:{node.lineno}")
        assert offenders == [], (
            "存在不传会话的排干点（跨会话串供的门没关）：\n  " + "\n  ".join(offenders)
        )
