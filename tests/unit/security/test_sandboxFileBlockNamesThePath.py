# -*- coding: utf-8 -*-
r"""文件类操作命中沙箱策略时，日志必须点名**是哪条路径**被拦——那条路径过去在日志里是空的。

现场（CI `cnb-8a0a-1k5kcrpsh-001` 与本地逐字一致）：`neurova/tool_executor.py:1646` 的
`logger.warning("文件操作命中沙箱策略但无文件沙箱后端，已阻止: %s", file_path)` 里的
`file_path` 在该函数作用域里**从未绑定**。形状上它是一处 pyflakes `undefined name`，实质是
一条**只写不读的取数**：同一次调用里 `extract_adjudicable_params` 明明返回了
`(键名, 值)` 清单，代码却把整份清单丢进 `_pathValues`（下划线＝声明不读），再凭一个幻影变量
去打日志。

所以这条不给"删掉日志"的出路（那是把报错挪走，教义第 2 条）：路径清单要**真的被消费**，
消费点是审计面的 warning——谁被拦、哪条路径，运维看得见。

判据取三条：
- 日志里必须出现那条路径的**值**（裁决面丢掉的那份清单被重新拿到）；
- 必须出现它的**键名**（多值时能指出是哪一格参数）；
- 无路径值时必须**不留 None 占位**（否则日志变成"已阻止: None"，比不说更坏）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from neurova.sandbox.exec_sandbox import SandboxSeverity
from neurova.security import governance

SHADOW = "/etc/passwd"


def _render(record: logging.LogRecord) -> str:
    """把一条日志渲染成"人看到的那一行"——记录本体不算数，`%s` 替换后的文本才算。"""
    try:
        return record.getMessage()
    except TypeError:  # 构造参数与占位符不匹配时，诚实暴露成原文，不静默吞掉
        return f"{record.msg!r} args={record.args!r}"


class _Verdict:
    """沙箱裁决的最小真实形状：decision=SANDBOX、severity、to_dict()。"""

    decision = governance.GovernanceDecision.SANDBOX
    severity = SandboxSeverity.READ_ONLY
    reasons = ["中风险,启用沙箱: 检测到系统路径访问"]

    def to_dict(self) -> dict:
        return {"decision": "sandbox", "severity": "medium", "reasons": list(self.reasons)}


def _executorWithSandboxVerdict():
    """真装配：真 ToolExecutor、真 `_governance_precheck`，只把治理裁决固定成 SANDBOX。

    不 mock `_governance_precheck` 本身——被测的那段就在它里面，替身会把判据一起替掉。
    """
    from neurova.tool_executor import ToolExecutor

    executor = ToolExecutor(agent_ref=None)
    executor._SESSION_SHELL_TOOLS = set()

    class _Governance:
        def evaluate_tool_call(self, tool_name, params, user_id=None, scan_all=False):
            return _Verdict()

    # 被测那一行的取数点在 `neurova.security.governance`：它在函数体内被 import，
    # 所以替身必须钉在**源模块**上（钉 tool_executor 的属性无效——那里从来没有这个名字）。
    governance.get_governance = lambda: _Governance()  # type: ignore[assignment]
    return executor


@pytest.fixture()
def _restoreGovernance():
    original = governance.get_governance
    yield
    governance.get_governance = original  # type: ignore[assignment]


class TestBlockedPathIsNamedInTheLog:
    def testWarningCarriesTheValueAndKeyOfTheBlockedPath(self, _restoreGovernance, caplog):
        executor = _executorWithSandboxVerdict()
        with caplog.at_level(logging.WARNING):
            result = asyncio.run(
                executor._governance_precheck("file_read", {"file_path": SHADOW})
            )

        assert result is not None and result.get("success") is False, "沙箱裁决必须仍然阻断"
        text = "\n".join(_render(record) for record in caplog.records)
        assert SHADOW in text, f"日志没点名被拦的路径值，实际读数：{text!r}"
        assert "file_path" in text, f"日志没点名被拦的路径键，实际读数：{text!r}"

    def testSecondPathValueIsAlsoNamed(self, _restoreGovernance, caplog):
        """一次调用带两条路径参数时，两条都要出现在日志里（清单不是只有第一条）。"""
        executor = _executorWithSandboxVerdict()
        params = {"file_path": SHADOW, "path": "/etc/shadow"}
        with caplog.at_level(logging.WARNING):
            asyncio.run(executor._governance_precheck("file_read", params))

        joined = " ".join(_render(record) for record in caplog.records)
        assert SHADOW in joined and "/etc/shadow" in joined, (
            f"第二条路径值在审计面消失（§6-284 甲案同一根因）：{joined!r}")

    def testNoPathValueLeavesNoNonePlaceholder(self, _restoreGovernance, caplog):
        """没有路径值时不许把 None 写进日志——那比不说更坏。"""
        executor = _executorWithSandboxVerdict()
        with caplog.at_level(logging.WARNING):
            asyncio.run(executor._governance_precheck("file_read", {"mode": "r"}))

        joined = " ".join(_render(record) for record in caplog.records)
        assert "None" not in joined, f"日志里出现 None 占位：{joined!r}"


class TestThePathListReallyReachesTheLogThroughTheRealEntry:
    """取数口闭环：日志里那串路径**必须**来自 `extract_adjudicable_params`，不是第二份写法。

    本格钉的是"同一份清单"，不是"某个字符串出现过"——改走另一份认键循环时它会红。
    """

    def testLoggedPathsEqualTheAdjudicableList(self, _restoreGovernance, caplog):
        executor = _executorWithSandboxVerdict()
        params = {"file_path": SHADOW, "path": "/etc/shadow"}
        expected = governance.extract_adjudicable_params("file_read", params, scan_all=False)[1]
        assert expected, "取数口本身空了，本格失去意义"

        with caplog.at_level(logging.WARNING):
            asyncio.run(executor._governance_precheck("file_read", params))

        joined = " ".join(_render(record) for record in caplog.records)
        for key, value in expected:
            assert value in joined and key in joined, (
                f"取数口给出的 ({key}, {value}) 没进审计日志：{joined!r}")
