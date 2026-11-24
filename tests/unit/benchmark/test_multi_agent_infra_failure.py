# -*- coding: utf-8 -*-
"""multi_agent 评测的「器械故障≠任务失败」红灯测试（reference_af P0-② 同契约扫荡）。

契约（与 suite_eval 同一词表）：
- runner 行新增 `failure_class`：执行派发异常＝"infra_answer"、判据异常＝
  "infra_checker"、正常量出＝""。**agent 返回体里的 error / swarm 治理拒绝**
  是被测系统的实测结局，不算器械故障（保持 ""）；
- `metrics.aggregate`：success_rate / mean_score 只对量出来的行（judged）求值，
  新增 `infra_failed` 计数；无器械故障时与旧口径逐字节一致。
"""

import pytest

from neurova.benchmark.multi_agent import BenchRunner, BenchmarkTask, TaskOutcome
from neurova.benchmark.multi_agent.metrics import aggregate


def _task(check=None):
    return BenchmarkTask(
        task_id="t1", suite="s", prompt="做点事",
        check=check or (lambda outcome: (True, 100.0, {})),
        description="样例",
    )


def _runner(agent):
    runner = BenchRunner(agent_id="测试", taskIsolatedMemory=False)
    runner._resolveAgent = lambda: agent  # 直接钉住解析面，不走 api 端点
    return runner


@pytest.mark.asyncio
async def testDispatchExceptionMarkedInfraAnswer():
    """agent.chat 抛异常＝评测器械故障，行标 failure_class=infra_answer。"""
    class _BoomAgent:
        def chat(self, *args, **kwargs):
            raise RuntimeError("llm channel down")

    row = await _runner(_BoomAgent()).runTask(_task(), "solo")
    assert row["failure_class"] == "infra_answer"
    assert row["passed"] is False
    assert "llm channel down" in row["error"]


@pytest.mark.asyncio
async def testCheckerExceptionMarkedInfraChecker():
    """判据自身崩溃＝器械故障，行标 failure_class=infra_checker。"""

    def badCheck(outcome: TaskOutcome):
        raise ValueError("checker bug")

    class _OkAgent:
        def chat(self, *args, **kwargs):
            return {"text": "正常报告"}

    row = await _runner(_OkAgent()).runTask(_task(check=badCheck), "solo")
    assert row["failure_class"] == "infra_checker"
    assert "checker bug" in row["details"].get("checker_error", "")


@pytest.mark.asyncio
async def testNormalRowHasEmptyFailureClass():
    class _OkAgent:
        def chat(self, *args, **kwargs):
            return {"text": "正常报告"}

    row = await _runner(_OkAgent()).runTask(_task(), "solo")
    assert row["failure_class"] == ""
    assert row["passed"] is True


@pytest.mark.asyncio
async def testAgentPayloadErrorIsMeasuredFailureNotInfra():
    """agent 返回体带 error（被测系统自己报错）＝实测结局，不算器械故障。"""
    class _ErrAgent:
        def chat(self, *args, **kwargs):
            return {"error": "agent internal failure", "text": ""}

    row = await _runner(_ErrAgent()).runTask(_task(), "solo")
    assert row["failure_class"] == ""
    assert row["passed"] is False
    assert row["error"]


def testAggregateExcludesInfraRowsFromDenominators():
    """均值/成功率只算量出来的行；器械故障单列 infra_failed 计数。"""
    rows = [
        {"mode": "solo", "passed": True, "score": 100.0, "failure_class": ""},
        {"mode": "solo", "passed": False, "score": 0.0, "failure_class": ""},
        {"mode": "solo", "passed": False, "score": 0.0, "failure_class": "infra_answer",
         "error": "RuntimeError: down"},
    ]
    agg = aggregate(rows)["solo"]
    assert agg["task_count"] == 3
    assert agg["infra_failed"] == 1
    assert agg["passed_count"] == 1
    assert agg["success_rate"] == pytest.approx(0.5)
    assert agg["mean_score"] == pytest.approx(50.0)


def testAggregateWithoutInfraMatchesLegacy():
    rows = [
        {"mode": "solo", "passed": True, "score": 100.0},
        {"mode": "solo", "passed": False, "score": 0.0},
    ]
    agg = aggregate(rows)["solo"]
    assert agg["infra_failed"] == 0
    assert agg["success_rate"] == pytest.approx(0.5)
    assert agg["mean_score"] == pytest.approx(50.0)
