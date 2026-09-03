"""工具执行熔断器测试（复用 LLM 层 CircuitBreaker，同源实现）。

语义要点（防呆设计随测试锁定）：
- 默认不安装：单例存在但无 guard/observer 注册 → 行为与未接入完全等价。
- install() 幂等：多次调用不重复注册。
- 策略性拒绝（治理 ASK/DENY/SANDBOX 拦截，result 含 governance/pending_approval）
  不计数为后端故障——把"用户/策略拒绝"误判为"服务故障"会熔断不该熔断的服务。
- 熔断打开 → guard DENY（deny-or-abstain 契约：只拒绝，不批准）。
"""

import time
import unittest
from unittest.mock import Mock

from neurova.security.monotonic_guard import GuardVerdict, get_monotonic_guards, reset_monotonic_guards
from neurova.security.governance import GovernanceDecision, GovernancePolicy, reset_governance
from neurova.agent.tool_pipeline import get_pipeline_observers, reset_pipeline_observers


class TestToolCircuitBreaker(unittest.TestCase):
    def setUp(self):
        reset_monotonic_guards()
        reset_pipeline_observers()
        reset_governance()
        from neurova.security import tool_circuit_breaker as mod

        mod.uninstall_tool_circuit_breaker(force=True)
        self.mod = mod

    def tearDown(self):
        reset_monotonic_guards()
        reset_pipeline_observers()
        reset_governance()
        self.mod.uninstall_tool_circuit_breaker(force=True)

    # ── 默认不安装：零行为变化 ────────────────────────────────

    def test_not_installed_by_default(self):
        """未安装：无守卫、无观察者，主链行为与未接入完全等价。"""
        self.assertIsNone(self.mod.get_tool_circuit_breaker())
        self.assertNotIn(
            "tool_circuit_breaker",
            [g.rule_id for g in get_monotonic_guards().list_guards()],
        )
        self.assertEqual(len(get_pipeline_observers().list_result_observers()), 0)

    # ── 安装与可逆性 ──────────────────────────────────────────

    def test_install_registers_guard_and_observer(self):
        handle = self.mod.install_tool_circuit_breaker()
        self.assertEqual(
            handle.breaker.name, "tools",
        )
        self.assertIn(
            "tool_circuit_breaker",
            [g.rule_id for g in get_monotonic_guards().list_guards()],
        )
        self.assertEqual(len(get_pipeline_observers().list_result_observers()), 1)

    def test_install_is_idempotent(self):
        h1 = self.mod.install_tool_circuit_breaker()
        h2 = self.mod.install_tool_circuit_breaker()
        self.assertIs(h1, h2)
        guards = [g for g in get_monotonic_guards().list_guards()
                  if g.rule_id == "tool_circuit_breaker"]
        self.assertEqual(len(guards), 1)
        self.assertEqual(len(get_pipeline_observers().list_result_observers()), 1)

    def test_uninstall_reverses_and_is_idempotent(self):
        self.mod.install_tool_circuit_breaker()
        self.mod.uninstall_tool_circuit_breaker()
        self.assertIsNone(self.mod.get_tool_circuit_breaker())
        self.assertNotIn(
            "tool_circuit_breaker",
            [g.rule_id for g in get_monotonic_guards().list_guards()],
        )
        self.assertEqual(len(get_pipeline_observers().list_result_observers()), 0)
        self.mod.uninstall_tool_circuit_breaker()  # 幂等
        self.mod.uninstall_tool_circuit_breaker(force=True)  # 清残留

    # ── 熔断语义（失败→打开→快速拒绝→半开恢复） ──────────────

    def test_failures_open_breaker_and_guard_denies(self):
        handle = self.mod.install_tool_circuit_breaker(failure_threshold=3)
        guard = handle.guard

        self.assertEqual(guard.check("shell", {}), GuardVerdict.ABSTAIN)
        for _ in range(2):
            handle.observer(Mock(success=False, result=None, errors=["x"]))
        self.assertEqual(guard.check("shell", {}), GuardVerdict.ABSTAIN)  # 2/3

        handle.observer(Mock(success=False, result=None, errors=["x"]))
        self.assertEqual(handle.breaker.get_state().value, "open")  # 3/3 打开
        self.assertEqual(guard.check("shell", {}), GuardVerdict.DENY)

    def test_open_breaker_rejects_through_governance(self):
        """端到端：熔断打开 → 守卫 DENY → 治理裁决 DENY（主链快速失败）。"""
        handle = self.mod.install_tool_circuit_breaker(failure_threshold=2)
        policy = GovernancePolicy()
        for _ in range(2):
            handle.observer(Mock(success=False, result=None, errors=["x"]))

        result = policy.evaluate_tool_call("shell", {"command": "echo ok"})
        self.assertEqual(result.decision, GovernanceDecision.DENY)
        self.assertIn("tool_circuit_breaker", "; ".join(result.reasons))

    def test_policy_denial_does_not_count_as_failure(self):
        """策略性拒绝（result 含 governance/pending_approval）不计为后端故障。"""
        handle = self.mod.install_tool_circuit_breaker(failure_threshold=2)
        handle.observer(Mock(success=False, result={"governance": {"decision": "deny"}}, errors=[]))
        handle.observer(Mock(success=False, result={"pending_approval": True}, errors=[]))
        self.assertEqual(handle.breaker.get_state().value, "closed")
        self.assertEqual(handle.guard.check("shell", {}), GuardVerdict.ABSTAIN)

    def test_success_in_half_open_closes_breaker(self):
        handle = self.mod.install_tool_circuit_breaker(
            failure_threshold=2, recovery_timeout=0.05)
        guard = handle.guard
        for _ in range(2):
            handle.observer(Mock(success=False, result=None, errors=["x"]))
        self.assertEqual(guard.check("shell", {}), GuardVerdict.DENY)

        # Windows time.sleep 粒度会实际短于请求值，轮询等待换状态而非硬睡
        deadline = time.monotonic() + 1.0
        while (handle.breaker.get_state().value != "half_open"
               and time.monotonic() < deadline):
            time.sleep(0.01)
        self.assertEqual(handle.breaker.get_state().value, "half_open")
        handle.observer(Mock(success=True, result={"content": "ok"}, errors=[]))
        self.assertEqual(handle.breaker.get_state().value, "closed")
        self.assertEqual(guard.check("shell", {}), GuardVerdict.ABSTAIN)

    def test_get_stats_exposes_breaker_health(self):
        handle = self.mod.install_tool_circuit_breaker(failure_threshold=2)
        handle.observer(Mock(success=False, result=None, errors=["x"]))
        stats = self.mod.get_tool_circuit_breaker_stats()
        self.assertEqual(stats["name"], "tools")
        self.assertEqual(stats["total_failure"], 1)
        self.assertIn("state", stats)


if __name__ == "__main__":
    unittest.main()
