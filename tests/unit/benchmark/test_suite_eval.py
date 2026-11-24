# -*- coding: utf-8 -*-
"""suite_eval 执行器单测（N3：benchmark 真评测执行器）。

红灯先行：`neurova.benchmark.suite_eval` 尚不存在，本档先钉行为契约——
- 全对 → score=1.0、tasks_correct==tasks_total；
- 部分对 → 比例分；
- LLM 异常 → 器械故障如实分类（failure_class=infra_answer）：行级记 0 分与
  error、计入 tasks_total、不中断 run；不进任务失败集合、不进均分母
  （P0-② 基础设施失败≠零分）；
- 判分口径：exactAnswer 精确匹配（归一化）、markersPresent 多标记比例给分；
- 时延用注入时钟可 deterministically 断言。
与 rag_eval / multi_agent 同构：判据注入、事实记录、不伪造分数。
"""
import pytest

from neurova.benchmark import suite_eval as suite_eval_module
from neurova.benchmark.suite_eval import (
    SuiteTask,
    clearSuiteBanks,
    exactAnswer,
    getSuiteTasks,
    markersPresent,
    registerSuiteTasks,
    runSuite,
    suiteWired,
)


@pytest.fixture(autouse=True)
def _restoreSeedBanks():
    """任务库是模块级全局：凡动过注册表的用例，事后必须复原种子库。"""
    saved = dict(suite_eval_module._SUITE_BANKS)
    yield
    suite_eval_module._SUITE_BANKS.clear()
    suite_eval_module._SUITE_BANKS.update(saved)


# ── 判分器 ─────────────────────────────────────────────────────────

def testExactAnswerNormalizesWhitespacePunctCase():
    check = exactAnswer("15")
    assert check("15")[0] is True
    assert check("  15。")[0] is True
    assert check("1 5")[0] is False
    assert check("十六")[0] is False


def testExactAnswerStringCaseInsensitive():
    check = exactAnswer("cba")
    assert check("CBA")[0] is True
    assert check("abc")[0] is False


def testMarkersPresentPartialCredit():
    check = markersPresent(("大海", "星星"))
    passed, score, details = check("夜空下大海与星星相映")
    assert passed is True and score == 1.0
    passed2, score2, details2 = check("只写了大海")
    assert passed2 is False and score2 == pytest.approx(0.5)
    assert details2["missing_markers"] == ["星星"]


# ── 执行器 ─────────────────────────────────────────────────────────

def _bank(correctPrefix: str):
    """三任务样例库：exactAnswer 判分，gold 分别为 a1/a2/a3。"""
    return [
        SuiteTask(task_id=f"t{i}", prompt=f"q{i}", check=exactAnswer(f"{correctPrefix}{i}"))
        for i in range(1, 4)
    ]


def testAllCorrectGivesFullScore():
    report = runSuite(_bank("a"), answerFn=lambda prompt: prompt.replace("q", "a"))
    assert report["status"] == "completed"
    assert report["tasks_total"] == 3
    assert report["tasks_correct"] == 3
    assert report["score"] == 1.0
    assert all(row["passed"] for row in report["per_task"])
    assert report["avg_latency_ms"] is not None and report["avg_latency_ms"] >= 0


def testPartialCorrectProportionalScore():
    # 只答对 q1、q2，q3 答错
    report = runSuite(_bank("a"), answerFn=lambda prompt: "a1" if prompt == "q1" else ("a2" if prompt == "q2" else "wrong"))
    assert report["tasks_total"] == 3
    assert report["tasks_correct"] == 2
    assert report["score"] == pytest.approx(2 / 3)


def testLlmExceptionFailsTaskHonestlyNotSkipped():
    def flaky(prompt: str) -> str:
        if prompt == "q2":
            raise RuntimeError("provider down")
        return prompt.replace("q", "a")

    report = runSuite(_bank("a"), answerFn=flaky)
    assert report["status"] == "completed"  # run 本身完成，失败事实如实记录
    assert report["tasks_total"] == 3  # 异常任务计入总数，不悄悄剔除
    # P0-②（reference_af 对照批）：取答通道崩溃＝评测器械故障（infra_answer），
    # 不折算任务失败——不进均分母，score 只算量出来的两题（都答对 ⇒ 1.0）。
    assert report["tasks_judged"] == 2
    assert report["tasks_infra_failed"] == 1
    assert report["tasks_failed"] == 0
    assert report["tasks_correct"] == 2
    assert report["score"] == pytest.approx(1.0)
    failed = report["per_task"][1]
    assert failed["passed"] is False
    assert failed["failure_class"] == "infra_answer"
    assert failed["score"] == 0.0  # 行级事实保留：该任务没有有效作答
    assert "RuntimeError" in failed["error"]
    assert "provider down" in failed["error"]
    assert report["per_task"][0]["error"] is None


def testCheckerExceptionDoesNotMaskExecutionFact():
    def badCheck(answer: str):
        raise ValueError("checker bug")

    tasks = [SuiteTask(task_id="t1", prompt="q1", check=badCheck)]
    report = runSuite(tasks, answerFn=lambda p: "任意回答")
    row = report["per_task"][0]
    assert row["passed"] is False and row["score"] == 0.0
    assert "checker bug" in row["details"].get("checker_error", "")


def testLatencyMeasuredWithInjectedClock():
    ticks = iter([0.0, 0.05, 0.05, 0.15])  # 任务1: 50ms，任务2: 100ms
    report = runSuite(_bank("a")[:2], answerFn=lambda p: "a1", clockFn=lambda: next(ticks))
    assert report["avg_latency_ms"] == pytest.approx(75.0)
    assert report["per_task"][0]["latency_ms"] == pytest.approx(50.0)
    assert report["per_task"][1]["latency_ms"] == pytest.approx(100.0)


def testLatencyMeasuredEvenWhenLlmRaises():
    ticks = iter([0.0, 0.2])

    def boom(prompt: str) -> str:
        raise RuntimeError("x")

    report = runSuite(_bank("a")[:1], answerFn=boom, clockFn=lambda: next(ticks))
    assert report["per_task"][0]["latency_ms"] == pytest.approx(200.0)


def testEmptyTaskListHonestNone():
    report = runSuite([], answerFn=lambda p: "x")
    assert report["tasks_total"] == 0
    assert report["score"] is None
    assert report["avg_latency_ms"] is None
    assert report["status"] == "completed"


def testAnswerFnMustBeProvidedNoFake():
    with pytest.raises(ValueError):
        runSuite(_bank("a"), answerFn=None)


def testLimitRunsFirstNTasks():
    report = runSuite(_bank("a"), answerFn=lambda p: p.replace("q", "a"), limit=2)
    assert report["tasks_total"] == 2
    assert [row["task_id"] for row in report["per_task"]] == ["t1", "t2"]


def testLimitClampedToBankSize():
    report = runSuite(_bank("a"), answerFn=lambda p: p.replace("q", "a"), limit=99)
    assert report["tasks_total"] == 3


def testAnswerSnippetTruncated():
    tasks = [SuiteTask(task_id="t1", prompt="q1", check=exactAnswer("x"))]
    report = runSuite(tasks, answerFn=lambda p: "长" * 1000)
    assert len(report["per_task"][0]["answer_snippet"]) <= 400


def testReportJsonSerializable():
    import json

    report = runSuite(_bank("a"), answerFn=lambda p: p.replace("q", "a"))
    json.dumps(report, ensure_ascii=False)


# ── 任务库注册表 ───────────────────────────────────────────────────

def testRegisterAndGetSuiteTasks():
    clearSuiteBanks()
    tasks = _bank("a")
    registerSuiteTasks("unit-suite", tasks)
    assert suiteWired("unit-suite") is True
    assert getSuiteTasks("unit-suite") == tasks
    assert suiteWired("no-such-suite") is False
    assert getSuiteTasks("no-such-suite") == []


def testRegisterReplacesExistingBank():
    clearSuiteBanks()
    registerSuiteTasks("unit-suite", _bank("a"))
    registerSuiteTasks("unit-suite", _bank("b"))
    assert len(getSuiteTasks("unit-suite")) == 3
    assert getSuiteTasks("unit-suite")[0].check("b1")[0] is True
