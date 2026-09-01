"""治理白名单（Whitelist）单元测试。

需求：白名单内的命令/工具免检放行（ALLOW），支持持久化与运行时增删。
优先级：tool_overrides > 白名单 > 内容检测。
"""

import json
import tempfile
import unittest
from unittest.mock import patch


def _with_enforced_platform():
    """P1-7：SANDBOX 分支断言统一 patch 平台隔离能力"""
    return patch("neurova.security.governance._platform_has_enforced_sandbox", return_value=True)
from unittest.mock import patch
from pathlib import Path

from neurova.security.governance import (
    GovernanceDecision,
    GovernancePolicy,
    reset_governance,
)


class TestWhitelistMatching(unittest.TestCase):
    """白名单匹配语义。"""

    def _policy(self, entries=None):
        return GovernancePolicy(
            whitelist_entries=entries
            if entries is not None
            else [{"pattern": "git status", "match_type": "prefix"}]
        )

    def test_prefix_match_bypasses_inspection(self):
        """命中前缀 → 直接 ALLOW，即使内容含可疑模式。"""
        policy = self._policy()
        # $() 命令替换本应触发 HIGH，但 git status 在白名单内
        result = policy.evaluate("git status && echo $(whoami)")
        self.assertEqual(result.decision, GovernanceDecision.ALLOW)
        self.assertTrue(any("白名单" in r for r in result.reasons))

    def test_non_matching_command_still_inspected(self):
        policy = self._policy()
        result = policy.evaluate("rm -rf /")
        self.assertEqual(result.decision, GovernanceDecision.DENY)

    def test_exact_match_type(self):
        policy = GovernancePolicy(
            whitelist_entries=[{"pattern": "ls", "match_type": "exact"}]
        )
        self.assertEqual(policy.evaluate("ls").decision, GovernanceDecision.ALLOW)
        # 非完全相等的命令不享受白名单：管道执行仍走检测（HIGH→SANDBOX）
        result = policy.evaluate("ls | sh")
        self.assertNotEqual(result.decision, GovernanceDecision.ALLOW)

    def test_regex_match_type(self):
        policy = GovernancePolicy(
            whitelist_entries=[
                {"pattern": r"^pytest\s+tests/", "match_type": "regex"}
            ]
        )
        self.assertEqual(policy.evaluate("pytest tests/unit -x").decision,
                         GovernanceDecision.ALLOW)

    def test_tool_scoped_entry_only_matches_that_tool(self):
        policy = GovernancePolicy(
            whitelist_entries=[
                {"pattern": "deploy.sh", "match_type": "prefix", "tool": "computer_shell"}
            ]
        )
        ok = policy.evaluate("deploy.sh && echo $(date)", tool_name="computer_shell")
        self.assertEqual(ok.decision, GovernanceDecision.ALLOW)
        # 其他工具不享受该条目：同样的命令仍触发检测（$() → HIGH）
        # P1-7：SANDBOX 分支以"平台有真隔离后端"为前提，patch 掉平台差异
        with _with_enforced_platform():
            other = policy.evaluate("deploy.sh && echo $(date)", tool_name="run_code")
        self.assertEqual(other.decision, GovernanceDecision.SANDBOX)

    def test_invalid_regex_ignored_safely(self):
        policy = GovernancePolicy(
            whitelist_entries=[{"pattern": "[unclosed", "match_type": "regex"}]
        )
        # 不抛异常；白名单未生效，危险命令照常被拦截
        result = policy.evaluate("rm -rf /")
        self.assertEqual(result.decision, GovernanceDecision.DENY)


class TestWhitelistPersistence(unittest.TestCase):
    """白名单持久化与运行时增删。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "governance_whitelist.json"
        reset_governance()

    def tearDown(self):
        reset_governance()

    def test_add_and_persist(self):
        policy = GovernancePolicy(whitelist_path=self.path)
        entry = policy.add_whitelist_entry(pattern="npm run test", match_type="prefix")
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["pattern"], "npm run test")
        self.assertEqual(entry["id"], data["entries"][0]["id"])

    def test_load_existing_file(self):
        self.path.write_text(
            json.dumps({"entries": [{"id": "w1", "pattern": "echo",
                                     "match_type": "exact"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        policy = GovernancePolicy(whitelist_path=self.path)
        self.assertEqual(policy.evaluate("echo").decision, GovernanceDecision.ALLOW)

    def test_remove_entry(self):
        policy = GovernancePolicy(whitelist_path=self.path)
        cmd = "dangerous-but-approved && echo x | sh"
        entry = policy.add_whitelist_entry(pattern="dangerous-but-approved")
        self.assertEqual(policy.evaluate(cmd).decision,
                         GovernanceDecision.ALLOW)
        self.assertTrue(policy.remove_whitelist_entry(entry["id"]))
        # 移除后同样的命令恢复检测（管道到 sh → SANDBOX；patch 平台有隔离）
        with _with_enforced_platform():
            result = policy.evaluate(cmd)
        self.assertEqual(result.decision,
                         GovernanceDecision.SANDBOX)
        self.assertFalse(policy.remove_whitelist_entry("nonexistent"))

    def test_corrupt_file_falls_back_to_empty(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        policy = GovernancePolicy(whitelist_path=self.path)
        self.assertEqual(policy.list_whitelist_entries(), [])

    def test_default_singleton_has_whitelist_support(self):
        from neurova.security.governance import get_governance

        gov = get_governance()
        self.assertIsInstance(gov.list_whitelist_entries(), list)
        entry = gov.add_whitelist_entry(pattern="whitelist-singleton-test",
                                        match_type="exact")
        try:
            self.assertEqual(gov.evaluate("whitelist-singleton-test").decision,
                             GovernanceDecision.ALLOW)
        finally:
            gov.remove_whitelist_entry(entry["id"])


if __name__ == "__main__":
    unittest.main()
