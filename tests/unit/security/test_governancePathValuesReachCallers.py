# -*- coding: utf-8 -*-
"""这条裁决**按哪些路径值裁的**，必须跟着裁决结果一起回到调用方。

改前实测（本档第一条红灯的原文）：

    evaluate_tool_call("write_file", {"file_path": "/etc/shadow", ...})
      verdict.to_dict().keys() → ['decision', 'finding_count', 'reasons', 'severity']

路径一格都没有。于是"被拦的是哪条路径"这条信息在结果面就已经丢了，消费方只能去
`reasons` 的散文里抠；抠法一换工具就哑（`unlink_file({"path": ...})` 抠出来是空）。
`tool_executor` 的文件保护支路此前正是这个形状：它从一个从未绑定的 `file_path` 打日志，
静态门禁报 F821，运行时被外层吞成 warning——文件类工具每到这一行就静默丢掉"拦了哪条路径"。

本档钉三层：
① 结果面带出路径值，且 `to_dict()` 一并带出（审计面才读得到）；
② 它与取数口 `extract_adjudicable_params` 同源——不是另算一遍；
③ 消费侧真走到那条拒绝支路时，日志里点到被拦的路径。
"""

from __future__ import annotations

import logging

import pytest

from neurova.security.governance import (
    GovernanceDecision,
    GovernancePolicy,
    extract_adjudicable_params,
)


def _verdictFor(toolName: str, params: dict, **kwargs):
    """走真实入口取裁决（不手工拼 `path_values`——那等于绕过装配点自证自己）。"""
    return GovernancePolicy().evaluate_tool_call(toolName, params, **kwargs)


class TestPathValuesReachTheResultFace:
    def testBlockedPathIsCarriedOnTheResult(self):
        """被拦的路径值随结果交回，且 `to_dict()` 里有它（审计面读的是这一份）。"""
        verdict = _verdictFor(
            "write_file",
            {"file_path": "/etc/shadow", "content": "x"},
            user_id="u-1",
        )
        assert verdict is not None, "受保护路径本该触发裁决"
        assert verdict.path_values, (
            "裁决按路径做过，结果面却没交回路径值——被拦的是哪条路径在这一层就丢了"
        )
        assert ("file_path", "/etc/shadow") in verdict.path_values

        payload = verdict.to_dict()
        assert payload.get("path_values") == [["file_path", "/etc/shadow"]], (
            "to_dict 没带出路径值，消费方只能回 reasons 的散文里抠：%r" % (payload,)
        )

    def testPathValuesComeFromTheSameExtractionPoint(self):
        """结果面的路径值 = 取数口 `extract_adjudicable_params` 的返回值（不生第二份口径）。"""
        params = {"file_path": "/etc/shadow", "path": "/root/.ssh/id_rsa", "content": "x"}
        _, expected = extract_adjudicable_params("write_file", params, scan_all=False)
        verdict = _verdictFor("write_file", params, user_id="u-1")
        assert verdict is not None
        assert verdict.path_values == expected, (
            "结果面与取数口各算了一遍：%r vs %r" % (verdict.path_values, expected)
        )

    def testNoPathValuesMeansNoPathWasAdjudicated(self):
        """没裁过路径就不许凭空填——空表是"没裁过"，不是"裁过但无值"。"""
        verdict = _verdictFor("exec_command", {"command": "ls -la"}, user_id="u-1")
        assert verdict is not None
        assert verdict.path_values == []
        assert "path_values" not in verdict.to_dict(), (
            "没裁过路径却给审计面塞一个空清单，读的人会当成'裁过、无值'"
        )


class TestConsumerNamesTheBlockedPath:
    def testFileGuardDenialLogsThePathItBlocked(self, caplog):
        """消费侧真走到拒绝支路时，日志点到被拦的路径（不是一句没有宾语的"已阻止"）。"""
        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)  # 只取这条支路，不起整套装配
        verdict = _verdictFor(
            "write_file",
            {"file_path": "/etc/shadow", "content": "x"},
            user_id="u-1",
        )
        assert verdict is not None and verdict.path_values

        with caplog.at_level(logging.WARNING):
            outcome = ToolExecutor._fileGuardDenial(executor, verdict)
        assert outcome["success"] is False
        assert any(
            "file_path=/etc/shadow" in record.getMessage() for record in caplog.records
        ), "拒绝支路的日志没说是哪条路径：%r" % [r.getMessage() for r in caplog.records]
