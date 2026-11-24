# -*- coding: utf-8 -*-
"""suite_eval 基础设施失败≠零分（reference_af 对照批 P0-②）红灯测试。

契约（Agent-S4 教训吸收，报告 docs/08-research/reference_af_..._2026-11-24.md §5）：
- 取答通道异常（LLM 429/超时/断连）＝**评测器械故障**，不是"该任务答错"；
- 判据自身异常同理——器械没量出来，不得折算成任务 0 分拖低均分；
- 行级事实保留（score 0.0、error 原文、不剔除、不中断），但聚合面必须分类：
  `failure_class` ∈ {"", "infra_answer", "infra_checker"}，新增
  tasks_judged / tasks_failed / tasks_infra_failed 三个计数；
- `score` 只对**量出来的任务**（judged）求均值；全量器械故障 ⇒ score=None
  （与空任务库同口径：没量到 ≠ 量出为零）。无器械故障时与旧口径逐字节一致。
"""

import pytest

from neurova.benchmark.suite_eval import SuiteTask, exactAnswer, runSuite


def _bank():
    return [
        SuiteTask(task_id=f"t{i}", prompt=f"q{i}", check=exactAnswer(f"a{i}"))
        for i in range(1, 4)
    ]


def testInfraAnswerExceptionClassifiedAndExcludedFromScore():
    """取答通道对 q2 崩溃：均分只算量出来的两题（都答对 ⇒ 1.0），不被 0 分拖成 2/3。"""
    def flaky(prompt: str) -> str:
        if prompt == "q2":
            raise RuntimeError("provider down")
        return prompt.replace("q", "a")

    report = runSuite(_bank(), answerFn=flaky)
    assert report["tasks_total"] == 3
    assert report["tasks_judged"] == 2
    assert report["tasks_correct"] == 2
    assert report["tasks_failed"] == 0
    assert report["tasks_infra_failed"] == 1
    assert report["score"] == pytest.approx(1.0)
    row = report["per_task"][1]
    assert row["failure_class"] == "infra_answer"
    assert row["passed"] is False and row["score"] == 0.0
    assert "provider down" in row["error"]


def testAllInfraFailuresScoreIsNoneNotZero():
    """通道全崩：没量出任何任务 ⇒ score=None（诚实缺席），不是伪造的 0.0。"""
    def boom(prompt: str) -> str:
        raise RuntimeError("channel dead")

    report = runSuite(_bank(), answerFn=boom)
    assert report["tasks_total"] == 3
    assert report["tasks_judged"] == 0
    assert report["tasks_infra_failed"] == 3
    assert report["score"] is None


def testCheckerExceptionClassifiedInfraChecker():
    """判据自身崩溃＝器械故障（infra_checker），同样不得折算任务 0 分。"""
    def badCheck(answer: str):
        raise ValueError("checker bug")

    tasks = [SuiteTask(task_id="t1", prompt="q1", check=badCheck)]
    report = runSuite(tasks, answerFn=lambda p: "任意回答")
    row = report["per_task"][0]
    assert row["failure_class"] == "infra_checker"
    assert row["passed"] is False and row["score"] == 0.0
    assert "checker bug" in row["details"].get("checker_error", "")
    assert report["tasks_judged"] == 0
    assert report["tasks_infra_failed"] == 1
    assert report["score"] is None


def testMixedJudgedAndInfraAggregation():
    """一题答对、一题答错、一题器械崩：均分 = (1.0 + 0.0) / 2 = 0.5，三类计数各归各位。"""
    def partlyDown(prompt: str) -> str:
        if prompt == "q3":
            raise TimeoutError("llm timeout")
        return prompt.replace("q", "a") if prompt == "q1" else "wrong"

    report = runSuite(_bank(), answerFn=partlyDown)
    assert report["tasks_total"] == 3
    assert report["tasks_judged"] == 2
    assert report["tasks_correct"] == 1
    assert report["tasks_failed"] == 1
    assert report["tasks_infra_failed"] == 1
    assert report["score"] == pytest.approx(0.5)
    classes = {row["task_id"]: row["failure_class"] for row in report["per_task"]}
    assert classes == {"t1": "", "t2": "", "t3": "infra_answer"}


def testNoInfraFailureKeepsLegacyAggregate():
    """无器械故障：新计数全零、failure_class 全空串，score 与旧口径一致。"""
    report = runSuite(_bank(), answerFn=lambda p: p.replace("q", "a"))
    assert report["tasks_judged"] == 3
    assert report["tasks_failed"] == 0
    assert report["tasks_infra_failed"] == 0
    assert report["score"] == pytest.approx(1.0)
    assert all(row["failure_class"] == "" for row in report["per_task"])
