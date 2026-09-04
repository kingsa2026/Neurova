"""工作流评估子系统（TDD — Dify 对标 §3.5「用 benchmark 跑道孵化工作流评估」）。

契约：
- EvalCase：输入样例 + 断言集（输出包含/等于/JSON path/节点状态）
- EvalSuite：样例集的持久化形态（dict 构建 / to_dict 往返）
- evaluate_workflow(storage, workflow_id, suite)：逐样例执行工作流并
  逐断言判定 → EvalReport（passed/failed/assertion_results/duration）
- 断言类型（不引入 LLM 判分——确定性断言优先，与 benchmark 哲学一致）：
  output_contains / output_equals / output_json_path / status_equals /
  node_completed
- 执行失败（工作流 FAILED/异常）→ 该样例 failed，reason 记录，不中断整批
"""

import pytest


class TestAssertions:
    def _eval_assert(self, kind, **kw):
        from neurova.collaboration.neurflow.workflow_evaluator import eval_assertion

        return eval_assertion(kind, **kw)

    def test_output_contains_pass_and_fail(self):
        check = self._eval_assert("output_contains", value="北京")
        assert check("今天北京晴") is True
        assert check("今天上海雨") is False

    def test_output_equals(self):
        check = self._eval_assert("output_equals", value={"a": 1})
        assert check({"a": 1}) is True
        assert check({"a": 2}) is False

    def test_output_json_path(self):
        check = self._eval_assert("output_json_path", path="weather.temp", value=25)
        assert check({"weather": {"temp": 25}}) is True
        assert check({"weather": {"temp": 30}}) is False
        assert check({"unrelated": 1}) is False

    def test_json_path_on_string_output_parses_json(self):
        """输出是 JSON 字符串时先解析再取路径"""
        check = self._eval_assert("output_json_path", path="temp", value=25)
        assert check('{"temp": 25}') is True

    def test_unknown_assertion_kind_raises(self):
        with pytest.raises(ValueError):
            self._eval_assert("no_such_kind", value=1)


class TestEvalSuite:
    def test_case_and_suite_roundtrip(self):
        from neurova.collaboration.neurflow.workflow_evaluator import EvalCase, EvalSuite

        case = EvalCase(
            name="晴天样例",
            inputs={"message": "查北京天气"},
            assertions=[
                {"kind": "output_contains", "value": "晴"},
                {"kind": "status_equals", "value": "completed"},
            ],
        )
        suite = EvalSuite(name="天气工作流评估", cases=[case])
        d = suite.to_dict()
        restored = EvalSuite.from_dict(d)
        assert restored.name == suite.name
        assert len(restored.cases) == 1
        assert restored.cases[0].assertions == case.assertions

    def test_suite_from_minimal_dict(self):
        from neurova.collaboration.neurflow.workflow_evaluator import EvalSuite

        suite = EvalSuite.from_dict({
            "name": "s",
            "cases": [{"name": "c1", "inputs": {"q": 1}, "assertions": [{"kind": "output_contains", "value": "x"}]}],
        })
        assert suite.cases[0].name == "c1"


class TestEvaluateWorkflow:
    @pytest.fixture
    def storage_with_workflow(self, tmp_path):
        """真实 neurflow storage + 一个 start→end 最小工作流"""
        import time as _time

        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )

        storage = NeurflowStorage(str(tmp_path / "neurflow.db"))
        wf = WorkflowDefinition(
            id="wf_eval_1",
            name="评估样例流",
            description="",
            version="1.0.0",
            nodes=[
                WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={"fields": []}),
                WorkflowNode(id="end", type="builtin:end", position={"x": 200, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="start", target="end")],
            variables=[],
            tags=[],
            category="general",
            author="eval",
            created_at=_time.time(),
            updated_at=_time.time(),
            status=WorkflowStatus.DRAFT,
        )
        storage.save_workflow(wf)
        return storage, wf

    @pytest.mark.asyncio
    async def test_evaluate_runs_and_asserts(self, storage_with_workflow):
        from neurova.collaboration.neurflow.workflow_evaluator import (
            EvalCase,
            EvalSuite,
            evaluate_workflow,
        )

        storage, wf = storage_with_workflow
        suite = EvalSuite(
            name="smoke",
            cases=[EvalCase(
                name="ok 案例",
                inputs={"q": "hi"},
                assertions=[
                    {"kind": "status_equals", "value": "completed"},
                    {"kind": "node_completed", "value": "start"},
                ],
            )],
        )
        report = await evaluate_workflow(storage, wf.id, suite)
        assert report.total == 1
        assert report.summary["passed"] + report.summary["failed"] == 1
        result = report.case_results[0]
        assert result["status"] in ("passed", "failed")
        assert isinstance(result["assertion_results"], list)
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_failing_workflow_does_not_abort_batch(self, storage_with_workflow):
        """断言失败的样例记 failed，后续样例继续执行"""
        from neurova.collaboration.neurflow.workflow_evaluator import (
            EvalCase,
            EvalSuite,
            evaluate_workflow,
        )

        storage, wf = storage_with_workflow
        suite = EvalSuite(
            name="batch",
            cases=[
                EvalCase(name="会失败", inputs={"q": "x"},
                         assertions=[{"kind": "output_contains", "value": "绝不可能出现"}]),
                EvalCase(name="会通过", inputs={"q": "y"},
                         assertions=[{"kind": "status_equals", "value": "completed"}]),
            ],
        )
        report = await evaluate_workflow(storage, wf.id, suite)
        statuses = [r["status"] for r in report.case_results]
        assert len(statuses) == 2, "两个样例都执行了"
        assert statuses[0] == "failed"
        assert statuses[1] == "passed"
        assert report.summary["failed"] == 1 and report.summary["passed"] == 1

    @pytest.mark.asyncio
    async def test_workflow_not_found(self, tmp_path):
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.collaboration.neurflow.workflow_evaluator import (
            EvalSuite,
            evaluate_workflow,
        )

        storage = NeurflowStorage(str(tmp_path / "neurflow.db"))
        report = await evaluate_workflow(storage, "ghost", EvalSuite(name="s", cases=[]))
        assert report.total == 0
        assert report.error == "workflow_not_found"

    @pytest.mark.asyncio
    async def test_report_persistence(self, storage_with_workflow, tmp_path):
        """报告可 JSON 落盘（benchmark 跑道历史复用）"""
        import json

        from neurova.collaboration.neurflow.workflow_evaluator import (
            EvalCase, EvalSuite, evaluate_workflow,
        )

        storage, wf = storage_with_workflow
        suite = EvalSuite(name="persist", cases=[
            EvalCase(name="c", inputs={}, assertions=[{"kind": "status_equals", "value": "completed"}]),
        ])
        report = await evaluate_workflow(storage, wf.id, suite)
        d = report.to_dict()
        round_tripped = json.loads(json.dumps(d))
        assert round_tripped["suite_name"] == "persist"
        assert "summary" in round_tripped
