"""多 agent 协作评测 harness（P0-1）单元测试。

红→绿契约：
- 任务注册表可注册/列举/清除；
- runner 以 solo 与 swarm 两种模式跑同一任务集（swarm 走真 SwarmManager 链路，含治理闸）；
- 聚合指标含 成功率/均分/不可解题识别/开销对照（swarm−solo）；
- 报告可出 JSON + Markdown（含逐任务行与聚合表）；
- swarm 治理拒绝（如空任务）计为该任务失败，不炸整个 run。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.benchmark.multi_agent import (
    BenchRunner,
    BenchmarkTask,
    TaskOutcome,
    clearTasks,
    listTasks,
    registerTask,
)
from neurova.benchmark.multi_agent.metrics import aggregate, compare
from neurova.benchmark.multi_agent.report import buildReport, renderMarkdown


def make_mock_agent(name="子Agent", reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


def make_smart_agent(name="评测假Agent"):
    """按任务提示词应答的假 agent：不可解题声明不可行；摘要任务给三节结构；其余给合规证据文摘。"""
    agent = MagicMock()
    agent.config.name = name

    async def _chat(prompt, *args, **kwargs):
        if "精确预测" in prompt or "不可行" in prompt:
            return {"text": "该问题不可行：缺少必要输入数据，无法给出数值。"}
        if "执行摘要" in prompt:
            return {"text": "【结论】X 领先。【依据】来源《A 报告》等三项证据。【风险】数据时效性。"}
        return {"text": COMPLIANT_REPORT}

    agent.chat = AsyncMock(side_effect=_chat)
    return agent


COMPLIANT_REPORT = (
    "## 调研结论\n"
    "1. 来源《A 报告》：指标 X=48；\n"
    "2. 来源《B 数据》：指标 Y=3.2；\n"
    "3. 来源《C 文档》：指标 Z=12%。\n"
)


def _markerChecker(requiredMarkers, infeasibleMarker=None):
    """种子任务用的最小切面判据：报告须含全部必需标记；不可解题须声明不可行且不编造。"""

    def _check(outcome: TaskOutcome):
        text = outcome.report or ""
        if infeasibleMarker is not None:
            ok = infeasibleMarker in text
            return ok, (100.0 if ok else 0.0), {"infeasible_declared": ok}
        missing = [m for m in requiredMarkers if m not in text]
        score = round((len(requiredMarkers) - len(missing)) / max(len(requiredMarkers), 1) * 100, 1)
        return (not missing), score, {"missing_markers": missing}

    return _check


SEED_TASKS = [
    BenchmarkTask(
        task_id="t1-sim-evidence-digest",
        suite="t1_sim",
        prompt="调研主题 X，输出带来源的证据文摘（至少 3 条，每条含来源与量化指标）。",
        check=_markerChecker(["来源《A 报告》", "来源《B 数据》", "来源《C 文档》"]),
        description="确定性模拟：证据文摘结构切面",
    ),
    BenchmarkTask(
        task_id="t1-sim-infeasible",
        suite="t1_sim",
        prompt="在不提供任何数据的情况下精确预测明年的销售额小数点后两位。",
        check=_markerChecker([], infeasibleMarker="不可行"),
        unsolvable=True,
        description="不可解题：正确声明不可行",
    ),
    BenchmarkTask(
        task_id="t3-rubric-exec-summary",
        suite="t3_rubric",
        prompt="撰写一段执行摘要，须含【结论】【依据】【风险】三节。",
        check=_markerChecker(["【结论】", "【依据】", "【风险】"]),
        description="量规判分打样：三节结构",
    ),
]


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def seeded():
    clearTasks()
    for t in SEED_TASKS:
        registerTask(t)
    yield
    clearTasks()


class TestTaskRegistry:
    def test_register_and_list(self, seeded):
        ids = [t.task_id for t in listTasks()]
        assert "t1-sim-evidence-digest" in ids
        assert "t1-sim-infeasible" in ids
        assert len(ids) == 3

    def test_duplicate_register_rejected(self, seeded):
        with pytest.raises(ValueError):
            registerTask(SEED_TASKS[0])


class TestRunnerBothModes:
    @pytest.mark.asyncio
    async def test_run_task_solo_and_swarm(self, swarm, seeded):
        agent = make_mock_agent(reply=COMPLIANT_REPORT)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            runner = BenchRunner(agent_id="researcher")
            solo = await runner.runTask(SEED_TASKS[0], mode="solo")
            swarm_res = await runner.runTask(SEED_TASKS[0], mode="swarm")

        assert solo["mode"] == "solo"
        assert solo["passed"] is True
        assert solo["score"] == 100.0
        assert solo["task_id"] == "t1-sim-evidence-digest"
        assert solo["elapsed_seconds"] >= 0

        assert swarm_res["mode"] == "swarm"
        assert swarm_res["passed"] is True
        assert swarm_res["subagent_id"].startswith("swarm_")

    @pytest.mark.asyncio
    async def test_swarm_governance_rejection_counts_as_failure(self, swarm, seeded):
        # 空任务被治理闸结构化拒绝 → 该任务计失败，runner 不抛出
        bad = BenchmarkTask(
            task_id="t1-sim-empty",
            suite="t1_sim",
            prompt="   ",
            check=_markerChecker([" anything "]),
        )
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            runner = BenchRunner(agent_id="researcher")
            res = await runner.runTask(bad, mode="swarm")
        assert res["passed"] is False
        assert res["error"]

    @pytest.mark.asyncio
    async def test_unsolvable_identification(self, swarm, seeded):
        agent = make_smart_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            runner = BenchRunner(agent_id="researcher")
            res = await runner.runTask(SEED_TASKS[1], mode="swarm")
        assert res["passed"] is True
        assert SEED_TASKS[1].unsolvable is True


class TestMetricsAndReport:
    @pytest.mark.asyncio
    async def test_aggregate_and_compare(self, swarm, seeded):
        agent = make_smart_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            runner = BenchRunner(agent_id="researcher")
            results = await runner.runTasks([t.task_id for t in SEED_TASKS], modes=("solo", "swarm"))

        assert len(results) == 6  # 3 任务 × 2 模式
        by_mode = aggregate(results)
        assert set(by_mode) == {"solo", "swarm"}
        for mode, m in by_mode.items():
            assert m["task_count"] == 3
            assert m["success_rate"] == pytest.approx(1.0)
            assert m["mean_score"] == pytest.approx(100.0)
            assert "mean_elapsed_seconds" in m
        # 不可解题识别
        assert by_mode["swarm"]["unsolvable_total"] == 1
        assert by_mode["swarm"]["unsolvable_identified"] == 1

        cmp = compare(results)
        assert "elapsed_delta_seconds" in cmp and "token_multiplier" in cmp

        report = buildReport(results, by_mode, cmp)
        md = renderMarkdown(report)
        assert "t1-sim-evidence-digest" in md
        assert "成功率" in md
        assert report["metrics"]["swarm"]["success_rate"] == pytest.approx(1.0)
