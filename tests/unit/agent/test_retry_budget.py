# -*- coding: utf-8 -*-
"""C3 红灯：进程治理——重试总预算、失败诚实分类、超时矩阵单源。

RetryBudget 核心判据：总预算超了即使次数没用完也 fail（不只数次数）；
classifyFailure 对 OOM 类失败给出诚实改写（明确标注资源耗尽，不掩盖）；
TIMEOUT_MATRIX 是握手/请求/取消/退出宽限的超时单源，acp_client 从此取值。
"""
import pytest

from neurova.agent.neuacp.process_governance import (
    TIMEOUT_MATRIX,
    RetryBudget,
    classifyFailure,
)


class TestRetryBudget:
    def test_budgetExhaustedBeforeAttemptsFailWithBudgetReason(self):
        budget = RetryBudget(max_attempts=5, total_budget_s=1.0)
        assert budget.canAttempt()
        budget.recordFailure(0.6)
        # 次数（1/5）与预算（0.6/1.0）都未尽，仍可尝试
        assert budget.canAttempt()
        budget.recordFailure(0.6)
        # 累计 1.2s 超总预算，次数才 2/5——本卡核心：预算超即 fail
        assert not budget.canAttempt()
        assert budget.attemptsUsed == 2
        assert budget.remainingBudgetS == 0.0
        reason = budget.exhaustedReason()
        assert reason is not None and "预算" in reason

    def test_attemptsExhaustedWithinBudgetFailWithAttemptsReason(self):
        budget = RetryBudget(max_attempts=2, total_budget_s=100.0)
        budget.recordFailure(0.1)
        assert budget.canAttempt()
        budget.recordFailure(0.1)
        # 预算充裕但次数用尽——fail 原因必须是次数
        assert not budget.canAttempt()
        assert budget.remainingBudgetS > 0.0
        reason = budget.exhaustedReason()
        assert reason is not None and "次数" in reason

    def test_successDoesNotRecordFailure(self):
        budget = RetryBudget(max_attempts=3, total_budget_s=10.0)
        # 成功路径不调用 recordFailure：计数与预算都不动
        assert budget.attemptsUsed == 0
        assert budget.canAttempt()
        assert budget.remainingBudgetS == pytest.approx(10.0)
        assert budget.exhaustedReason() is None

    def test_firstAttemptAlwaysAllowedOnFreshBudget(self):
        budget = RetryBudget(max_attempts=1, total_budget_s=30.0)
        assert budget.canAttempt()
        budget.recordFailure(30.0)
        # 默认 max_attempts=1：首败即终（行为与无重试一致）
        assert not budget.canAttempt()

    def test_remainingBudgetNeverNegative(self):
        budget = RetryBudget(max_attempts=5, total_budget_s=1.0)
        budget.recordFailure(2.5)
        assert budget.remainingBudgetS == 0.0


class TestClassifyFailure:
    def test_oomTextIsRewrittenHonestly(self):
        text = "FATAL ERROR: Reached heap limit - Allocation failed - JavaScript heap out of memory"
        verdict = classifyFailure(text)
        assert verdict["kind"] == "oom"
        reason = verdict["honest_reason"]
        # 诚实改写：明确标注资源耗尽，且不掩盖原始证据
        assert "资源耗尽" in reason
        assert "heap out of memory" in reason

    def test_oomChinesePattern(self):
        verdict = classifyFailure("进程因内存不足被系统杀死")
        assert verdict["kind"] == "oom"
        assert "资源耗尽" in verdict["honest_reason"]

    def test_timeoutKind(self):
        verdict = classifyFailure("ACP request timeout: session/prompt")
        assert verdict["kind"] == "timeout"

    def test_crashKind(self):
        verdict = classifyFailure("agent exited (code=-1073741510)")
        assert verdict["kind"] == "crash"

    def test_unknownKindKeepsOriginalReason(self):
        text = "some unrelated failure text"
        verdict = classifyFailure(text)
        assert verdict["kind"] == "unknown"
        assert text in verdict["honest_reason"]


class TestTimeoutMatrix:
    def test_matrixHasFourKeys(self):
        assert set(TIMEOUT_MATRIX) == {"handshake", "request", "cancel", "terminate_grace"}

    def test_requestAndTerminateMatchLegacyDefaults(self):
        # 与 acp_client 历史默认一致（行为不变）
        assert TIMEOUT_MATRIX["request"] == 30.0
        assert TIMEOUT_MATRIX["terminate_grace"] == 5.0

    def test_acpClientConstantsComeFromMatrix(self):
        # 单源判据：acp_client 的两个常量改为从矩阵取值
        from neurova.agent.neuacp import acp_client

        assert acp_client._DEFAULT_REQUEST_TIMEOUT == TIMEOUT_MATRIX["request"]
        assert acp_client._TERMINATE_WAIT_S == TIMEOUT_MATRIX["terminate_grace"]
