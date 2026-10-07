# -*- coding: utf-8 -*-
"""P2-8 前置：并发槽位的记账必须是"谁占谁还"，不能"每次问就占一格"。

发现的形态（读 `_check_concurrency_limit` 得，再看下面三条红灯坐实）：

    current_count = self._active_agents.get(model_name, 0)
    if current_count < MAX:                      # MAX=6
        self._active_agents[model_name] = current_count + 1   # ← 判一次加一次
        return YieldDecision(should_yield=False)

唯一会减的地方是 `unregister_agent`（:141），而 `record_operation_complete` **不减**、
也没有任何生产调用方去 unregister。也就是说：

- 槽位是"读一次占一格"，不是"跑一个操作占一格"；同一个 Agent 问 6 次就把它所用模型的
  6 个槽全吃掉，第 7 次起对**所有**同模型 Agent 恒判 `CONCURRENT_AGENT` 让位。
- 这正是让位闸接进回合链后要撞上的东西：一个 Agent 的 10 次重试就能把整条模型的
  并发额度永久占满，之后每个回合都等 200 秒再挂起——把"防碰撞"变成"自我锁死"。

今天没爆只因为这条链没接线（`check_yield_rules` 生产侧只有 REST `/coordination/*` 在调，
外部问一次占一格，但没人按它的话停下）。所以**先修记账，再接闸**。

三条判据都打在真 `GlanceYieldChecker` 上，不 mock 业务对象。
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.collaboration.glance_yield_rules import GlanceYieldChecker  # noqa: E402


def _freshChecker() -> GlanceYieldChecker:
    return GlanceYieldChecker()


def _ask(checker: GlanceYieldChecker, agentId: str, model: str = "gpt-x"):
    return checker.check_yield_rules(
        agent_id=agentId, model_name=model, proposed_operations=[f"op-{agentId}"]
    )


class TestConcurrencySlotAccounting:
    def testRepeatedChecksByOneAgentDoNotEatEverySlot(self):
        """同一个 Agent 反复问判据不该把模型额度吃光——问 7 次仍必须放行。"""
        checker = _freshChecker()

        for _ in range(7):
            decision = _ask(checker, "agent-single")
            assert decision.should_yield is False, (
                "同一个 Agent 问了几次就把自己的模型额度占满：记账把『查询』当成了『开工』"
                f"（active_per_model={checker.get_stats()['active_per_model']}）"
            )

    def testOnlyStartedOperationsOccupyASlot(self):
        """槽位只由 record_operation_start 占、由 record_operation_complete 还。"""
        checker = _freshChecker()
        limit = GlanceYieldChecker.DEFAULT_MAX_CONCURRENT_AGENTS
        checker.register_agent("agent-busy", "gpt-x")
        checker.register_agent("agent-late", "gpt-x")

        _ask(checker, "agent-idle")
        assert checker.get_stats()["active_per_model"].get("gpt-x", 0) == 0, (
            "只问了一句（没开工）就占了槽位——查询不该改变占用"
        )

        checker.record_operation_start("agent-busy", "op-1")
        assert checker.get_stats()["active_per_model"].get("gpt-x", 0) == 1, (
            "真开工却没占槽：并发上限形同虚设"
        )

        checker.record_operation_complete("agent-busy", "op-1", success=True)
        assert checker.get_stats()["active_per_model"].get("gpt-x", 0) == 0, (
            "操作完成没还槽：跑够 6 个之后该模型永久满员"
        )

        for index in range(limit):
            checker.register_agent(f"agent-{index}", "gpt-x")
            checker.record_operation_start(f"agent-{index}", f"op-{index}")
        blocked = _ask(checker, "agent-late")
        assert blocked.should_yield is True, "占满 limit 个操作后，后来者必须被让位"
        assert blocked.reason.value == "concurrent_agent"

        checker.record_operation_complete("agent-0", "op-0", success=True)
        assert _ask(checker, "agent-late").should_yield is False, (
            "还了一个槽却还是让位——释放路径没接回计数"
        )

    def testLeakedSlotIsReapedInsteadOfRottingForever(self, monkeypatch):
        """崩在半路、没走到 complete 的操作必须会自己过期，不能永久占位。

        仓里对同一形态已有答案：`core/agent_run_store` 用 lease + 启动 reconcile
        兜住"记账泄漏"。内存计数器同样要有租约，否则一次异常就永久少一格。
        """
        checker = _freshChecker()
        monkeypatch.setattr(GlanceYieldChecker, "ACTIVE_OP_LEASE_SECONDS", 0.05)
        checker.register_agent("agent-crashed", "gpt-x")
        checker.record_operation_start("agent-crashed", "op-leak")
        assert checker.get_stats()["active_per_model"].get("gpt-x", 0) == 1

        time.sleep(0.08)
        decision = _ask(checker, "agent-next")

        assert decision.should_yield is False, (
            f"泄漏的槽位没有租约回收，永久占着（active={checker.get_stats()['active_per_model']}）"
        )
        assert checker.get_stats()["active_per_model"].get("gpt-x", 0) == 0, (
            "回收没落地：占位仍在计数里"
        )


    def testStartWithoutPinDoesNotOccupyABucket(self, caplog):
        """归因不到模型就不占槽。

        塞进一个 "unknown" 公共桶，等于让所有没注册过的调用方共用一份额度——那正是
        本批要消灭的"挤进同一个桶"形态，只是换了个位置复发。
        """
        checker = _freshChecker()
        limit = GlanceYieldChecker.DEFAULT_MAX_CONCURRENT_AGENTS

        for index in range(limit + 2):
            checker.record_operation_start(f"orphan-{index}", f"op-{index}")

        assert checker.get_stats()["active_per_model"] == {}, (
            f"无 pin 的开工仍占了槽：{checker.get_stats()['active_per_model']}"
        )
        assert _ask(checker, "whoever").should_yield is False, "phantom 桶把后来者挡下了"
