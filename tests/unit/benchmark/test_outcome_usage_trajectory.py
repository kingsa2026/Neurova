# -*- coding: utf-8 -*-
"""S1 评测地基补全（1A usage 回传 + 1B 轨迹效率判据）红灯档。

红→绿契约（方案 docs/04-plans/2026-11-17-surpass-reference-implementation-plan.md §S1）：
- TaskOutcome 含 usage（promptTokens/completionTokens/totalTokens/elapsedSeconds/
  steps/toolCalls）与 trajectory（toolsUsed 等轨迹事实）字段；
- 判据 DSL expect_trajectory(maxSteps/maxToolCalls/allowedTools) 可约束超步数任务；
- runner 逐任务回传 usage：mock 桩填 0，loop 回传（usage_accounting 增量）出真数；
- 报告聚合含 usage/轨迹列。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.benchmark.multi_agent import BenchRunner, BenchmarkTask, TaskOutcome
from neurova.benchmark.multi_agent.metrics import aggregate
from neurova.benchmark.multi_agent.report import buildReport, renderMarkdown
from neurova.benchmark.multi_agent.tasks import expect_trajectory


USAGE_KEYS = ("promptTokens", "completionTokens", "totalTokens", "elapsedSeconds", "steps", "toolCalls")


def _outcome(**overrides) -> TaskOutcome:
    base = dict(task_id="t1-sim-evidence-digest", mode="solo", report="正文")
    base.update(overrides)
    return TaskOutcome(**base)


class TestOutcomeCarriesUsageAndTrajectory:
    def test_outcome_carries_usage_and_trajectory(self):
        """红灯主判据：TaskOutcome 必须携带 usage 与 trajectory 字段，
        且 expect_trajectory 能把超步数任务判失败。"""
        outcome = _outcome(
            usage={
                "promptTokens": 120,
                "completionTokens": 80,
                "totalTokens": 200,
                "elapsedSeconds": 1.5,
                "steps": 7,
                "toolCalls": 3,
            },
            trajectory={"toolsUsed": ["web_search", "read_file"]},
        )
        # 1A：usage 字段在，且六个键齐
        assert isinstance(outcome.usage, dict), "TaskOutcome 缺 usage 字段"
        for key in USAGE_KEYS:
            assert key in outcome.usage, f"usage 缺 {key}"
        # 1B：轨迹事实在
        assert outcome.trajectory["toolsUsed"] == ["web_search", "read_file"]

        # 超步数任务必须被 expect_trajectory 判失败
        overBudget = expect_trajectory(maxSteps=3)
        passed, score, details = overBudget(outcome)
        assert passed is False, "steps=7 超过 maxSteps=3，必须判失败"
        assert score == 0.0
        assert details["violations"], "判据 details 须写明违反了哪条约束"

        # 预算内任务通过
        okOutcome = _outcome(usage={k: 1 for k in USAGE_KEYS}, trajectory={"toolsUsed": []})
        passed2, score2, _ = expect_trajectory(maxSteps=3, maxToolCalls=2)(okOutcome)
        assert passed2 is True
        assert score2 == 100.0

    def test_outcome_defaults_are_empty_dicts(self):
        outcome = _outcome()
        assert outcome.usage == {}
        assert outcome.trajectory == {}

    def test_expect_trajectory_max_tool_calls(self):
        outcome = _outcome(usage={"toolCalls": 9, "steps": 1}, trajectory={"toolsUsed": ["a"] * 9})
        passed, _, details = expect_trajectory(maxToolCalls=4)(outcome)
        assert passed is False
        assert any("toolCalls" in v for v in details["violations"])

    def test_expect_trajectory_allowed_tools(self):
        outcome = _outcome(
            usage={"toolCalls": 2, "steps": 1},
            trajectory={"toolsUsed": ["web_search", "shell_exec"]},
        )
        passed, _, details = expect_trajectory(allowedTools=("web_search", "read_file"))(outcome)
        assert passed is False, "越权工具必须被判据拦下"
        assert any("shell_exec" in v for v in details["violations"])

        passedOk, _, _ = expect_trajectory(allowedTools=("web_search", "shell_exec"))(outcome)
        assert passedOk is True

    def test_expect_trajectory_composes_with_base_checker(self):
        def basePass(outcome):
            return True, 88.0, {"missing_markers": []}

        def baseFail(outcome):
            return False, 20.0, {"missing_markers": ["【结论】"]}

        outcome = _outcome(usage={"steps": 2, "toolCalls": 0}, trajectory={"toolsUsed": []})
        composed = expect_trajectory(maxSteps=3, base=basePass)
        passed, score, details = composed(outcome)
        assert passed is True
        assert score == 88.0, "轨迹合规时保留基础判据分数"
        assert "trajectory" in details, "合成判据 details 须带轨迹子项"

        passedFail, scoreFail, _ = expect_trajectory(maxSteps=1, base=basePass)(outcome)
        assert passedFail is False and scoreFail == 0.0, "轨迹违例一票否决"

        passedBase, scoreBase, _ = expect_trajectory(maxSteps=9, base=baseFail)(outcome)
        assert passedBase is False and scoreBase == 20.0, "基础判据不过，合成仍不过"


class TestRunnerCarriesUsage:
    def _mockAgent(self, reply="合规报告正文"):
        agent = MagicMock()
        agent.config.name = "评测假Agent"
        agent.chat = AsyncMock(return_value={"text": reply})
        return agent

    def test_runner_solo_populates_usage_mock_fills_zero(self):
        """mock 桩：无真实 LLM 记账 → token/步数/工具数填 0，elapsed 为正。"""
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        task = BenchmarkTask(
            task_id="t1-sim-usage", suite="t1_sim", prompt="任意任务",
            check=lambda outcome: (True, 100.0, {}),
        )
        with patch("neurova.api.endpoints.get_agent_instance", return_value=self._mockAgent()):
            result = asyncio.run(BenchRunner(agent_id="评测假Agent").runTask(task, mode="solo"))

        usage = result.get("usage")
        assert isinstance(usage, dict), "runner 结果须带 usage"
        for key in USAGE_KEYS:
            assert key in usage, f"usage 缺 {key}"
        assert usage["promptTokens"] == 0 and usage["completionTokens"] == 0
        assert usage["totalTokens"] == 0 and usage["steps"] == 0 and usage["toolCalls"] == 0
        assert usage["elapsedSeconds"] >= 0, "耗时如实记录（瞬时 mock 可为 0）"

    def test_runner_solo_reads_loop_usage_delta(self):
        """loop 回传：chat 执行期入账 usage_accounting → runner 取增量出真数。"""
        from neurova.core.usage_accounting import get_usage_accounting, reset_usage_accounting

        reset_usage_accounting()
        agent = self._mockAgent()

        async def _chat(prompt, *args, **kwargs):
            # 模拟 loop/LLM 客户端在执行期入账两轮调用
            get_usage_accounting().record(
                model="bench-mock", prompt_tokens=100, completion_tokens=50,
                provider="mock", response_id="r1",
            )
            get_usage_accounting().record(
                model="bench-mock", prompt_tokens=30, completion_tokens=20,
                provider="mock", response_id="r2",
            )
            return {"text": "合规报告正文", "tool_messages": [
                {"type": "tool_call", "tool_name": "web_search"},
                {"type": "tool_result", "tool_name": "web_search"},
            ]}

        agent.chat = AsyncMock(side_effect=_chat)
        task = BenchmarkTask(
            task_id="t1-sim-usage-live", suite="t1_sim", prompt="任意任务",
            check=lambda outcome: (True, 100.0, {}),
        )
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = asyncio.run(BenchRunner(agent_id="评测假Agent").runTask(task, mode="solo"))

        usage = result["usage"]
        assert usage["promptTokens"] == 130
        assert usage["completionTokens"] == 70
        assert usage["totalTokens"] == 200
        assert usage["steps"] == 2, "LLM 调用次数 = loop 回传 calls 增量"
        assert usage["toolCalls"] == 1, "tool_call 消息计数（tool_result 不计）"
        assert result["trajectory"]["toolsUsed"] == ["web_search"]

    def test_metrics_aggregate_usage_columns(self):
        results = [
            {"mode": "solo", "passed": True, "score": 100.0, "effort": "standard",
             "elapsed_seconds": 1.0, "tokens": 200,
             "usage": {"promptTokens": 130, "completionTokens": 70, "totalTokens": 200,
                       "elapsedSeconds": 1.0, "steps": 2, "toolCalls": 1}},
            {"mode": "solo", "passed": False, "score": 0.0, "effort": "standard",
             "elapsed_seconds": 2.0, "tokens": 100,
             "usage": {"promptTokens": 60, "completionTokens": 40, "totalTokens": 100,
                       "elapsedSeconds": 2.0, "steps": 1, "toolCalls": 0}},
        ]
        agg = aggregate(results)
        solo = agg["solo"]
        assert solo["total_tokens"] == 300
        assert solo["total_prompt_tokens"] == 190
        assert solo["total_completion_tokens"] == 110
        assert solo["total_steps"] == 3
        assert solo["total_tool_calls"] == 1

    def test_report_renders_usage_and_trajectory_columns(self):
        results = [
            {"task_id": "t1-sim-usage", "suite": "t1_sim", "mode": "solo", "unsolvable": False,
             "passed": True, "score": 100.0, "details": {}, "error": None, "rejected": False,
             "rejection_code": "", "subagent_id": "", "elapsed_seconds": 1.0, "tokens": 200,
             "effort": "standard", "effort_source": "fallback_standard", "report_snippet": "x",
             "usage": {"promptTokens": 130, "completionTokens": 70, "totalTokens": 200,
                       "elapsedSeconds": 1.0, "steps": 2, "toolCalls": 1},
             "trajectory": {"toolsUsed": ["web_search"]}},
        ]
        metrics = aggregate(results)
        report = buildReport(results, metrics, {"available": False}, taskIsolatedMemory=True)
        assert report["task_isolated_memory"] is True, "报告须注明记忆是否按任务隔离"
        md = renderMarkdown(report)
        assert "步数" in md and "工具数" in md, "明细表须含轨迹效率列"
        assert "web_search" in md, "逐任务轨迹（工具序列）须可见"


class TestTaskIsolatedMemory:
    """S1-1C：taskIsolatedMemory 记忆隔离（正式对比默认开启，报告注明）。"""

    def _capturingAgent(self, sessionIds):
        agent = MagicMock()
        agent.config.name = "评测假Agent"

        async def _chat(prompt, *args, **kwargs):
            sessionIds.append(kwargs.get("session_id"))
            return {"text": "正文"}

        agent.chat = AsyncMock(side_effect=_chat)
        return agent

    def test_solo_isolation_gives_unique_session_per_task(self):
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        sessionIds = []
        agent = self._capturingAgent(sessionIds)
        task = BenchmarkTask(
            task_id="t1-iso", suite="t1_sim", prompt="p",
            check=lambda outcome: (True, 100.0, {}),
        )
        runner = BenchRunner(agent_id="评测假Agent")  # 默认开启隔离
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            asyncio.run(runner.runTask(task, mode="solo"))
            asyncio.run(runner.runTask(task, mode="solo"))
        assert len(sessionIds) == 2
        assert len(set(sessionIds)) == 2, "每任务必须拿到独立会话命名空间"
        assert all(s and s.startswith("bench_t1-iso_") for s in sessionIds)

    def test_solo_isolation_off_keeps_legacy_call(self):
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        sessionIds = []
        agent = self._capturingAgent(sessionIds)
        task = BenchmarkTask(
            task_id="t1-iso-off", suite="t1_sim", prompt="p",
            check=lambda outcome: (True, 100.0, {}),
        )
        runner = BenchRunner(agent_id="评测假Agent", taskIsolatedMemory=False)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            asyncio.run(runner.runTask(task, mode="solo"))
        assert sessionIds == [None], "关闭隔离时不传会话键（沿旧默认行为）"

    def test_run_all_with_report_saves_and_annotates_isolation(self, tmp_path, monkeypatch):
        from neurova.benchmark.multi_agent import clearTasks, registerTask
        from neurova.benchmark.multi_agent.report import loadReport

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        reset = tmp_path / "benchmark" / "multi_agent"
        assert not reset.exists()

        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        clearTasks()
        registerTask(BenchmarkTask(
            task_id="t1-iso-report", suite="t1_sim", prompt="p",
            check=lambda outcome: (True, 100.0, {}),
        ))
        agent = MagicMock()
        agent.config.name = "评测假Agent"
        agent.chat = AsyncMock(return_value={"text": "正文"})
        try:
            with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
                report = asyncio.run(BenchRunner(agent_id="评测假Agent").runAllWithReport())
        finally:
            clearTasks()

        assert report["task_isolated_memory"] is True
        assert report["report_id"] and report["report_path"]
        saved = loadReport(report["report_id"])
        assert saved is not None, "报告须已原子落盘（只读端点的数据源）"
        assert saved["metrics"]["solo"]["total_steps"] >= 0
        assert "usage" in saved["tasks"][0] and "trajectory" in saved["tasks"][0]
