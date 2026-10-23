# -*- coding: utf-8 -*-
r"""裁决结果必须把"这一次调用里哪些参数被按路径裁决过"带出去——否则拒绝语只能报半句。

实测形状（改动前，`evaluate_tool_call("write_file", {"file_path": "/etc/shadow", ...})`）：

    decision: ASK
    to_dict:  ['decision', 'finding_count', 'reasons', 'severity']   ← 路径一格都没有
    finding:  "写入受保护路径: /etc/shadow"

`finding.message` 里**恰好**带着路径，于是调用方可以改从 message 里抠字符串——实测这条
抠法在 `unlink_file({"path": ...})` 上会漏：守卫报的是"删除受保护路径"，而抠串取到的是空。
同一实现在参数面上逐个值裁决，却在结果面上只回一句散文，取值口就此断在 `to_dict()`。

判据分三层（缺一层都可能是橡皮章）：
  1. 路径真的进了裁决结果：键名与值都带得出来，且 `to_dict()` 里读得到；
  2. 与本模块自己的取数口**同一份**：`evaluate(...)` 的结果路径集合 == 取数口给出的集合；
  3. 消费方能靠它说人话：`tool_executor` 的拒绝语里出现那个路径（活体走一遍真门）。
"""

from __future__ import annotations

import asyncio
import unittest

from neurova.security.governance import GovernancePolicy, extract_adjudicable_params


class TestPathValuesAreCarriedOutOfTheVerdict(unittest.TestCase):
    def setUp(self):
        # 引擎按 AUTO 构造（与生产装配同形）：HIGH 在无真隔离后端时会升成 DENY。
        # 哪种裁决都行——判据只问"路径带没带出来"，不问裁到哪一级。
        self.policy = GovernancePolicy()

    def testVerdictKeepsEveryPathValueItAdjudicated(self):
        verdict = self.policy.evaluate(
            "", tool_name="write_file", path_values=[("file_path", "/etc/shadow")])
        self.assertEqual([(k, v) for k, v in verdict.path_values], [("file_path", "/etc/shadow")])
        self.assertEqual(verdict.to_dict().get("path_values"), [["file_path", "/etc/shadow"]],
                         "to_dict() 没把路径带出去——消费方只能去 reasons 里抠散文")

    def testTwoPathsInOneCallBothSurvive(self):
        """一次调用带两条路径参数，两条都要在结果面上——这是 §6-284 甲案那条链的出口。"""
        verdict = self.policy.evaluate(
            "", tool_name="write_file",
            path_values=[("file_path", "/etc/shadow"), ("path", "/etc/hosts")])
        self.assertEqual([v for _, v in verdict.path_values], ["/etc/shadow", "/etc/hosts"])

    def testVerdictPathsMatchTheSingleExtractionPoint(self):
        """结果面的路径集合必须等于取数口 `extract_adjudicable_params` 给出的那一份。"""
        params = {"file_path": "/etc/shadow", "content": "x"}
        _, expected = extract_adjudicable_params("write_file", params, scan_all=False)
        verdict = self.policy.evaluate("", tool_name="write_file", path_values=expected)
        self.assertEqual(list(verdict.path_values), list(expected))


class TestDenialSpeaksThePathItBlocked(unittest.TestCase):
    """消费侧活体：真 `ToolExecutor._governance_precheck` 走一遍，拒绝语里要有那个路径。"""

    def testRefusalNamesThePathItBlocked(self):
        from neurova.tool_executor import ToolExecutor

        # 替身只提供身份读取这一格（生产装配点照旧由 ToolExecutor 自己创建治理单例）
        class _AgentStub:
            _current_user_id = "alice"
            agent_id = "default"
            config = None

        executor = ToolExecutor(_AgentStub())
        params = {"file_path": "/etc/shadow", "content": "x"}
        outcome = asyncio.run(executor._governance_precheck("write_file", params))
        self.assertIsNotNone(outcome, "受保护路径竟被放行——这一格根本没走到拒绝支路")
        self.assertIn("/etc/shadow", outcome.get("error", ""),
                      f"拒绝语没点名被拦的路径，人只能看到半句散文：{outcome}")


if __name__ == "__main__":
    unittest.main()
