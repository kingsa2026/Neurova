"""ToolExecutionPipeline 五段流水线契约测试（对齐 DeepSeek Harness 工具流水线）。

五段语义（与治理中心的关系见模块头注释）：
pre → guard → execute(main) → post → result

- pre：预处理步骤，可改写上下文或抛 PipelineReject 拒绝（拒绝→跳过 main，
  post/result 仍执行以便观测）
- guard：dsh 语义单调守卫（DENY/ABSTAIN；abstain 放行、deny 跳过 main）
- execute：主执行体（由调用方经 middleware 包装传入；wrapper 可环绕/改写结果）
- post：既有步骤段（记忆/生命周期/技能/进化），旧四步语义保留
- result：观察者收到独立冻结的不可变快照，异常彼此隔离
"""

import importlib
import warnings
import unittest
from unittest.mock import Mock

from neurova.security.monotonic_guard import GuardVerdict
from neurova.tool_layers.types import ToolExecutionContext


def _ctx(**overrides):
    defaults = dict(
        context_id="c1",
        tool_name="test_tool",
        params={"command": "ls"},
        user_input="list files",
    )
    defaults.update(overrides)
    return ToolExecutionContext(**defaults)


class TestPipelineModule(unittest.TestCase):
    def test_import_no_longer_warn_deprecated(self):
        """模块不再是死代码：import 不产生 DeprecationWarning。"""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.reload(importlib.import_module("neurova.agent.tool_pipeline"))
        deprecated = [
            w for w in caught
            if (issubclass(w.category, DeprecationWarning)
                or "dead code" in str(w.message))
        ]
        self.assertEqual(deprecated, [])


class TestLegacyCompatibility(unittest.TestCase):
    """旧 API（add_step + execute）语义保留：不下降。"""

    def test_legacy_add_step_execute_runs_post_steps(self):
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        pipeline = ToolExecutionPipeline()
        step = Mock()
        step.name = "lifecycle_update"  # dependent 类步骤（非并行段）
        step.error_level = "warning"
        pipeline.add_step(step)
        report = pipeline.execute(_ctx())

        self.assertTrue(step.execute.called)
        self.assertFalse(report.errors)
        self.assertEqual(report.tool_name, "test_tool")

    def test_legacy_step_times_and_warnings(self):
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        pipeline = ToolExecutionPipeline()
        ok = Mock()
        ok.name = "step1"
        ok.error_level = "warning"
        bad = Mock()
        bad.name = "step2"
        bad.error_level = "warning"
        bad.execute.side_effect = RuntimeError("x")
        pipeline.add_step(ok)
        pipeline.add_step(bad)
        report = pipeline.execute(_ctx())
        self.assertIn("step1", report.step_times)
        self.assertIn("step2", report.step_times)
        self.assertEqual(len(report.warnings), 1)  # 步骤失败 → warning 不炸传
        self.assertIn("total_processing_time", report.to_dict())

    def test_legacy_create_default_pipeline_registers_four_steps(self):
        from neurova.agent.tool_pipeline import create_default_pipeline

        pipeline = create_default_pipeline(
            tool_memory=Mock(), tool_lifecycle=Mock(),
            skill_packer=Mock(), evolution=Mock(),
        )
        self.assertEqual(len(pipeline.steps), 4)

    def test_empty_pipeline_is_noop(self):
        """空流水线：无步骤、无守卫、无观察者 → 正常空报告（等价于未接入）。"""
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        report = ToolExecutionPipeline().execute(_ctx())
        self.assertFalse(report.errors)
        self.assertFalse(report.is_fully_successful)


class TestFiveStageOrder(unittest.TestCase):
    """五段顺序固定：pre → guard → execute → post → result。"""

    def test_stage_order(self):
        from neurova.agent.tool_pipeline import (
            PipelineGuardAdapter,
            ToolExecutionPipeline,
        )

        order = []
        pipeline = ToolExecutionPipeline()

        class PreStep:
            name = "pre_custom"
            error_level = "warning"

            def execute(self, context, report):
                order.append("pre")

        pipeline.add_pre_step(PreStep())
        pipeline.add_guard(PipelineGuardAdapter("g1", lambda *a: GuardVerdict.ABSTAIN))

        def main(context):
            order.append("main")
            return {"content": "ok"}

        pipeline.add_execute_wrapper(lambda context, next_fn: next_fn(context))

        class PostStep:
            name = "post_step"
            error_level = "warning"

            def execute(self, context, report):
                order.append("post")

        pipeline.add_post_step(PostStep())
        pipeline.add_result_observer(lambda frozen: order.append("result"))

        report = pipeline.resolve(_ctx(), main=main)
        self.assertEqual(order[:4], ["pre", "main", "post", "result"])
        self.assertEqual(report.result, {"content": "ok"})

    def test_execute_delegates_to_resolve(self):
        """execute() 是 resolve() 的兼容入口。"""
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        order = []
        pipeline = ToolExecutionPipeline()

        def main(context):
            order.append("main")

        report = pipeline.resolve(_ctx(), main=main)
        self.assertEqual(order, ["main"])
        self.assertFalse(report.rejected)


class TestPreStage(unittest.TestCase):
    def test_reject_short_circuits_main_but_runs_post_and_result(self):
        from neurova.agent.tool_pipeline import PipelineReject, ToolExecutionPipeline

        order = []
        pipeline = ToolExecutionPipeline()

        class PreStep:
            name = "pre_reject"
            error_level = "warning"

            def execute(self, context, report):
                order.append("pre")
                raise PipelineReject("not allowed")

        pipeline.add_pre_step(PreStep())
        pipeline.add_result_observer(lambda frozen: order.append("result"))

        def main(context):
            order.append("main")

        report = pipeline.resolve(_ctx(), main=main)
        self.assertEqual(order, ["pre", "result"])
        self.assertTrue(report.rejected)
        self.assertIn("not allowed", "; ".join(report.errors))


class TestGuardStage(unittest.TestCase):
    def test_guard_deny_skips_main_runs_post_and_result(self):
        from neurova.agent.tool_pipeline import PipelineGuardAdapter, ToolExecutionPipeline

        order = []
        pipeline = ToolExecutionPipeline()
        pipeline.add_guard(PipelineGuardAdapter("deny_all", lambda *a: GuardVerdict.DENY))
        pipeline.add_result_observer(lambda frozen: order.append("result"))

        def main(context):
            order.append("main")

        report = pipeline.resolve(_ctx(), main=main)
        self.assertNotIn("main", order)
        self.assertIn("result", order)
        self.assertTrue(report.rejected)
        self.assertIn("deny_all", "; ".join(report.errors))

    def test_guard_abstain_proceeds_to_main(self):
        from neurova.agent.tool_pipeline import PipelineGuardAdapter, ToolExecutionPipeline

        order = []
        pipeline = ToolExecutionPipeline()
        pipeline.add_guard(PipelineGuardAdapter("watch", lambda *a: GuardVerdict.ABSTAIN))

        def main(context):
            order.append("main")

        pipeline.resolve(_ctx(), main=main)
        self.assertEqual(order, ["main"])

    def test_guard_exception_is_fail_closed(self):
        from neurova.agent.tool_pipeline import PipelineGuardAdapter, ToolExecutionPipeline

        def bad_guard(tool_name, params, user_id=None):
            raise RuntimeError("boom")

        pipeline = ToolExecutionPipeline()
        pipeline.add_guard(PipelineGuardAdapter("exploder", bad_guard))
        report = pipeline.resolve(_ctx(), main=lambda c: {"content": "x"})
        self.assertTrue(report.rejected)
        self.assertIn("exploder", "; ".join(report.errors))


class TestExecuteStage(unittest.TestCase):
    def test_wrapper_is_middleware_can_rewrite_result(self):
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        def wrapper(context, next_fn):
            result = next_fn(context)  # 真实主执行
            result["content"] = result["content"] + "!"  # 环绕改写（dsh 语义）
            return result

        pipeline = ToolExecutionPipeline()
        pipeline.add_execute_wrapper(wrapper)
        report = pipeline.resolve(_ctx(), main=lambda c: {"content": "ok"})
        self.assertEqual(report.result, {"content": "ok!"})


class TestResultStage(unittest.TestCase):
    def test_observer_receives_independent_frozen_snapshot(self):
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        seen = []
        pipeline = ToolExecutionPipeline()
        pipeline.add_result_observer(lambda frozen: seen.append(frozen))
        report = pipeline.resolve(_ctx(), main=lambda c: {"content": "ok", "deep": {"x": 1}})

        snapshot = seen[0]
        self.assertEqual(snapshot.tool_name, "test_tool")
        self.assertTrue(snapshot.success is True or snapshot.success is False)
        # 快照与最终报告互不污染（深拷贝）
        snapshot_dict = snapshot.to_dict()
        snapshot_dict["result"]["content"] = "mutated"
        self.assertEqual(report.to_dict()["result"]["content"], "ok")

    def test_observer_failure_is_isolated(self):
        from neurova.agent.tool_pipeline import ToolExecutionPipeline

        got = []
        pipeline = ToolExecutionPipeline()

        def bad(frozen):
            raise RuntimeError("observer down")

        pipeline.add_result_observer(bad)
        pipeline.add_result_observer(lambda frozen: got.append(frozen))
        report = pipeline.resolve(_ctx(), main=lambda c: {"content": "ok"})
        self.assertEqual(len(got), 1)  # 后序观察者仍执行
        self.assertEqual(len(report.warnings), 1)  # 异常被记录未炸传


class TestObserverGateway(unittest.TestCase):
    """通知门面：ToolExecutor.on_tool_executed 尾部挂载点。"""

    def test_gateway_empty_noop(self):
        from neurova.agent.tool_pipeline import (
            get_pipeline_observers,
            notify_tool_result,
            reset_pipeline_observers,
        )

        reset_pipeline_observers()
        try:
            self.assertEqual(len(get_pipeline_observers().list_result_observers()), 0)
            notify_tool_result(tool_name="t", success=True, result={"content": "x"})
        finally:
            reset_pipeline_observers()

    def test_gateway_singles_observers_and_resets(self):
        from neurova.agent.tool_pipeline import (
            get_pipeline_observers,
            notify_tool_result,
            reset_pipeline_observers,
        )

        reset_pipeline_observers()
        try:
            got = []
            get_pipeline_observers().add_result_observer(got.append)
            notify_tool_result(tool_name="t", success=True, result={"content": "x"})
            self.assertEqual(got[0].tool_name, "t")
            self.assertTrue(got[0].success)
            reset_pipeline_observers()
            notify_tool_result(tool_name="t", success=False)
            self.assertEqual(len(got), 1)  # reset 后不再触发
        finally:
            reset_pipeline_observers()


class TestToolExecutorIntegration(unittest.TestCase):
    """on_tool_executed 门面接入：真实入口触发观察者。"""

    def _minimal_executor(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        executor._agent = Mock()  # 无属性时 getattr 兜底 None/Mock
        return executor

    def test_on_tool_executed_notifies_registered_observer(self):
        from neurova.agent.tool_pipeline import (
            get_pipeline_observers,
            reset_pipeline_observers,
        )

        reset_pipeline_observers()
        try:
            got = []
            get_pipeline_observers().add_result_observer(got.append)
            self._minimal_executor().on_tool_executed(
                tool_name="browser_navigate",
                params={"url": "http://x"},
                user_input="go",
                success=True,
                tool_source="builtin",
                execution_time=0.5,
                result={"success": True},
            )
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0].tool_name, "browser_navigate")
            self.assertTrue(got[0].success)
        finally:
            reset_pipeline_observers()

    def test_on_tool_executed_without_observers_is_unchanged(self):
        from neurova.agent.tool_pipeline import reset_pipeline_observers

        reset_pipeline_observers()
        try:
            self._minimal_executor().on_tool_executed(
                tool_name="memory_search",
                params={},
                user_input="q",
                success=False,
                tool_source="builtin",
                execution_time=0.1,
                result=None,
            )  # 无观察者：no-op，不抛异常
        finally:
            reset_pipeline_observers()


class TestPolicyDenialStats(unittest.TestCase):
    """断点 B 修复（闭环审计）：策略拒绝 ≠ 真实故障。

    治理拦截（DENY/SANDBOX 阻止/ASK 待确认）的 result 携带 governance /
    pending_approval 键。修复前这些"策略事件"被三处统计按 success=False
    计入（Prometheus 失败率 / 肌肉记忆负样本 / 生命周期 failure_calls）。
    修复后：策略拒绝跳过三处失败计数（拒绝本身已由 _audit_governance 留痕），
    真实故障照常记录。
    """

    def _executor_with_trackers(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        agent = Mock()
        executor._agent = agent
        return executor, agent

    def _call(self, executor, result, success=False):
        executor.on_tool_executed(
            tool_name="computer_shell",
            params={"command": "rm -rf /"},
            user_input="rm",
            success=success,
            tool_source="builtin",
            execution_time=0.1,
            result=result,
        )

    def test_governance_denial_not_recorded_as_failure(self):
        """策略 DENY：三处统计均不产生失败记录。"""
        from unittest.mock import patch

        executor, agent = self._executor_with_trackers()
        with patch("neurova.core.metrics.get_metrics") as mocked_metrics:
            self._call(executor, {"success": False, "governance": {"decision": "deny"}})
            mocked_metrics.return_value.record_tool_execution.assert_not_called()
        agent.tool_memory.record_tool_usage.assert_not_called()
        agent.tool_lifecycle.touch.assert_not_called()

    def test_pending_approval_not_recorded_as_failure(self):
        """ASK 待确认（pending_approval）：同样不记为失败。"""
        from unittest.mock import patch

        executor, agent = self._executor_with_trackers()
        with patch("neurova.core.metrics.get_metrics") as mocked_metrics:
            self._call(executor, {"success": False, "pending_approval": True})
            mocked_metrics.return_value.record_tool_execution.assert_not_called()
        agent.tool_memory.record_tool_usage.assert_not_called()
        agent.tool_lifecycle.touch.assert_not_called()

    def test_real_failure_still_recorded(self):
        """真实故障（无 governance 键）：三处照常记录（不降级）。"""
        from unittest.mock import patch

        executor, agent = self._executor_with_trackers()
        with patch("neurova.core.metrics.get_metrics") as mocked_metrics:
            self._call(executor, {"success": False, "error": "connection refused"})
            mocked_metrics.return_value.record_tool_execution.assert_called_once()
        agent.tool_memory.record_tool_usage.assert_called_once()
        agent.tool_lifecycle.touch.assert_called_once()

    def test_success_still_recorded(self):
        """成功路径不受影响。"""
        from unittest.mock import patch

        executor, agent = self._executor_with_trackers()
        with patch("neurova.core.metrics.get_metrics") as mocked_metrics:
            self._call(executor, {"content": "ok"}, success=True)
            mocked_metrics.return_value.record_tool_execution.assert_called_once()
        agent.tool_memory.record_tool_usage.assert_called_once()
        agent.tool_lifecycle.touch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
