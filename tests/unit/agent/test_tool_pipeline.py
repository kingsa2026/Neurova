"""工具执行结果观察门面契约测试（T-09 处置后）。

**本文件在 T-09 死码处置批（Issue #174 / #310）之后的覆盖范围**：
只剩一件真事——把工具执行结果以**冻结快照**形态分发给注册的观察者。

- `notify_tool_result(...)`：写入侧唯一接入点，被 `ToolExecutor.on_tool_executed` 尾部调用；
- `get_pipeline_observers()`：读取侧门面，`security/tool_circuit_breaker.py` 经它挂观察者；
- `ToolExecutionReport`：发给观察者的对外契约形状（`frozen()` 深拷贝快照）。

**已退场的五段框架测试随能力一并退役**（不是被删掉当清理）：pre / guard / execute / post
四段的注册入口生产侧全仓零调用，`ToolExecutionPipeline` 本身零引用——留着它们的测试
会让人以为这条能力还有调用方。退役的逐条论证与反向控制见
`tests/unit/tools/test_t09_pipeline_face_ruling.py`（常驻判据）。
"""

import importlib
import unittest
from unittest.mock import Mock


class TestPipelineModule(unittest.TestCase):
    def test_import_no_longer_warn_deprecated(self):
        """模块不再是死代码：import 不产生 DeprecationWarning。"""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.reload(importlib.import_module("neurova.agent.tool_pipeline"))
        deprecated = [
            w for w in caught
            if (issubclass(w.category, DeprecationWarning)
                or "dead code" in str(w.message))
        ]
        self.assertEqual(deprecated, [])


class TestObserverGateway(unittest.TestCase):
    """通知门面：`ToolExecutor.on_tool_executed` 尾部挂载点（真面）。"""

    def setUp(self):
        """每个用例前清空全局观察者。

        `reset_pipeline_observers()` 已随五段框架退场（生产侧零调用），
        故测试改走注册表自己的 `clear()` —— 它是**仍在役**的清理入口，
        不再为测试专门保留一个生产零调用的重置函数。
        """
        from neurova.agent.tool_pipeline import get_pipeline_observers

        self.observers = get_pipeline_observers()
        self.observers.clear()

    def test_gateway_empty_is_noop(self):
        """空注册表 = 零行为变化（未接入的默认形态）。"""
        from neurova.agent.tool_pipeline import notify_tool_result

        self.assertEqual(len(self.observers.list_result_observers()), 0)
        notify_tool_result(tool_name="t", success=True, result={"content": "x"})
        self.assertEqual(len(self.observers.list_result_observers()), 0)

    def test_gateway_singles_observers_and_clear_removes_them(self):
        from neurova.agent.tool_pipeline import notify_tool_result

        got = []
        self.observers.add_result_observer(got.append)
        notify_tool_result(tool_name="t", success=True, result={"content": "x"})
        self.assertEqual(got[0].tool_name, "t")
        self.assertTrue(got[0].success)

        self.observers.clear()
        notify_tool_result(tool_name="t", success=False)
        self.assertEqual(len(got), 1)  # clear 后不再触发

    def test_observer_receives_independent_frozen_snapshot(self):
        """观察者拿到的是**深拷贝快照**：改动它不污染源报告。"""
        from neurova.agent.tool_pipeline import notify_tool_result

        seen = []
        self.observers.add_result_observer(seen.append)
        notify_tool_result(
            tool_name="t", success=True,
            result={"content": "ok", "deep": {"x": 1}},
        )
        snapshot = seen[0]
        self.assertEqual(snapshot.tool_name, "t")
        snapshot_dict = snapshot.to_dict()
        snapshot_dict["result"]["deep"]["x"] = 999
        self.assertEqual(seen[0].to_dict()["result"]["deep"]["x"], 1)

    def test_observer_failure_is_isolated(self):
        """单个观察者抛异常不得影响后序观察者（故障隔离）。"""
        from neurova.agent.tool_pipeline import notify_tool_result

        got = []

        def bad(_frozen):
            raise RuntimeError("observer down")

        self.observers.add_result_observer(bad)
        self.observers.add_result_observer(got.append)
        notify_tool_result(tool_name="t", success=True, result={"content": "ok"})
        self.assertEqual(len(got), 1)

    def test_disposer_removes_only_its_own_observer(self):
        """`add_result_observer` 返回的 disposer 只摘自己那一个。"""
        got_a, got_b = [], []
        dispose_a = self.observers.add_result_observer(got_a.append)
        self.observers.add_result_observer(got_b.append)
        dispose_a()

        from neurova.agent.tool_pipeline import notify_tool_result

        notify_tool_result(tool_name="t", success=True)
        self.assertEqual(got_a, [])
        self.assertEqual(len(got_b), 1)


class TestFiveStageFrameIsGone(unittest.TestCase):
    """五段框架与重置出口**真删**——不留「标注保留」的折中。"""

    def test_frame_symbols_are_gone(self):
        """逐名断言模块属性不存在：删的是实现，不是把它标成 deprecated。"""
        import neurova.agent.tool_pipeline as tp

        for symbol in ("ToolExecutionPipeline", "PipelineConfig",
                       "PipelineGuardAdapter", "ToolExecutionStep",
                       "PipelineReject", "reset_pipeline_observers"):
            self.assertFalse(hasattr(tp, symbol), f"{symbol} 已随 T-09 处置退场")

    def test_result_face_survives(self):
        """真面必须仍在——退役不得连带砍断结果分发。"""
        import neurova.agent.tool_pipeline as tp

        for symbol in ("notify_tool_result", "get_pipeline_observers",
                       "ToolExecutionReport", "PipelineObserversRegistry"):
            self.assertTrue(hasattr(tp, symbol), f"真面 {symbol} 被连带删除")


class TestToolExecutorIntegration(unittest.TestCase):
    """on_tool_executed 门面接入：真实入口触发观察者。"""

    def _minimal_executor(self):
        from neurova.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)
        executor._agent = Mock()  # 无属性时 getattr 兜底 None/Mock
        return executor

    def test_on_tool_executed_notifies_registered_observer(self):
        from neurova.agent.tool_pipeline import get_pipeline_observers

        get_pipeline_observers().clear()
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
            get_pipeline_observers().clear()

    def test_on_tool_executed_without_observers_is_unchanged(self):
        from neurova.agent.tool_pipeline import get_pipeline_observers

        get_pipeline_observers().clear()
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
            get_pipeline_observers().clear()


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
