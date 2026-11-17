# -*- coding: utf-8 -*-
"""P3-3 APEX 式 T3 任务集扩充 + effort_inference 变量报告 单元测试。

覆盖：
- T3 量规任务集扩到 ≥10（财务/分析族），原种子保留、不可解题在册；
- registerBuiltinSuites 幂等（重复登记不翻倍）；
- 每条 T3 任务都有提示词与判据；
- runner 逐任务附 effort/effort_source（resolveQueryEffort 单源）；
- aggregate 输出 by_effort 分档聚合（档位/通过/成功率/均分）；
- Markdown 报告渲染思考档位变量节。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.benchmark.multi_agent import BenchRunner, clearTasks, getTask, listTasks
from neurova.benchmark.multi_agent.metrics import aggregate
from neurova.benchmark.multi_agent.report import buildReport, renderMarkdown
from neurova.benchmark.multi_agent.suites import registerBuiltinSuites


@pytest.fixture(autouse=True)
def cleanRegistry():
    clearTasks()
    yield
    clearTasks()


class TestApexTaskSet:
    def test_t3_suite_expanded_to_ten_plus(self):
        registerBuiltinSuites()
        t3 = listTasks(suite="t3_rubric")
        assert len(t3) >= 10, f"T3 量规任务应不少于 10 条，实得 {len(t3)}"
        ids = {t.task_id for t in t3}
        assert "t3-rubric-exec-summary" in ids, "原种子任务必须保留"
        assert "t3-rubric-dcf-valuation" in ids, "APEX 新增财务任务在册"
        assert "t3-rubric-infeasible-price" in ids, "T3 不可解题在册"

    def test_registration_is_idempotent(self):
        registerBuiltinSuites()
        first = len(listTasks(suite="t3_rubric"))
        registerBuiltinSuites()
        assert len(listTasks(suite="t3_rubric")) == first, "重复登记不得翻倍（幂等）"

    def test_every_t3_task_has_prompt_and_checker(self):
        registerBuiltinSuites()
        for task in listTasks(suite="t3_rubric"):
            assert task.prompt.strip(), f"{task.task_id} 缺提示词"
            assert callable(task.check), f"{task.task_id} 缺判据"
            assert task.suite == "t3_rubric"

    def test_infeasible_task_declared_unsolvable(self):
        registerBuiltinSuites()
        assert getTask("t3-rubric-infeasible-price").unsolvable is True

    def test_seed_module_no_longer_exposes_dead_registrar(self):
        import neurova.benchmark.multi_agent.suites.seed_tasks as seed

        assert not hasattr(seed, "registerSeedTasks"), \
            "registerSeedTasks 零调用方，改造成 SEED_TASKS 数据面后不得残留死入口"
        assert hasattr(seed, "SEED_TASKS")


class TestEffortReporting:
    @pytest.mark.asyncio
    async def test_runner_attaches_effort_per_task(self):
        registerBuiltinSuites()
        agent = MagicMock()
        agent.config.name = "评测假Agent"
        agent.chat = AsyncMock(return_value={"text": "【结论】x。【依据】y。【风险】z。"})
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            runner = BenchRunner(agent_id="评测假Agent")
            result = await runner.runTask(getTask("t3-rubric-exec-summary"), mode="solo")
        assert result["effort"] in ("light", "deep", "standard")
        assert result["effort_source"] in ("explicit", "inferred", "fallback_standard")

    @pytest.mark.asyncio
    async def test_runall_registers_builtin_suites(self):
        agent = MagicMock()
        agent.config.name = "评测假Agent"
        agent.chat = AsyncMock(return_value={"text": "该问题不可行：数据不足。"})
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            results = await BenchRunner(agent_id="评测假Agent").runAll(modes=("solo",))
        ids = {r["task_id"] for r in results}
        assert "t3-rubric-dcf-valuation" in ids, "runAll 入口应自动登记内置任务集"

    def test_aggregate_breaks_down_by_effort(self):
        results = [
            {"mode": "solo", "passed": True, "score": 100.0, "effort": "deep",
             "elapsed_seconds": 1.0, "tokens": 10},
            {"mode": "solo", "passed": False, "score": 0.0, "effort": "deep",
             "elapsed_seconds": 1.0, "tokens": 10},
            {"mode": "solo", "passed": True, "score": 50.0, "effort": "light",
             "elapsed_seconds": 1.0, "tokens": 5},
        ]
        agg = aggregate(results)
        byEffort = agg["solo"]["by_effort"]
        assert byEffort["deep"]["task_count"] == 2
        assert byEffort["deep"]["passed_count"] == 1
        assert byEffort["deep"]["success_rate"] == 0.5
        assert byEffort["deep"]["mean_score"] == 50.0
        assert byEffort["light"]["task_count"] == 1
        assert byEffort["light"]["success_rate"] == 1.0

    def test_markdown_renders_effort_section(self):
        metrics = {"solo": {
            "task_count": 2, "passed_count": 1, "success_rate": 0.5, "mean_score": 50.0,
            "unsolvable_total": 0, "unsolvable_identified": 0,
            "mean_elapsed_seconds": 1.0, "total_tokens": 10, "error_count": 0,
            "by_effort": {"deep": {"task_count": 2, "passed_count": 1,
                                   "success_rate": 0.5, "mean_score": 50.0}},
        }}
        report = buildReport([], metrics, {"available": False})
        md = renderMarkdown(report)
        assert "思考档位" in md
        assert "deep" in md and "0.5" in md
