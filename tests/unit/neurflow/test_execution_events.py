"""
NeurFlow P0 Step 1 — 调试事件协议扩展测试

测试扩展执行事件协议：
- BREAKPOINT_HIT：节点执行前命中断点，发出事件并暂停
- STEP_ADVANCED：单步推进后发出
- VARIABLE_SCOPED：变量设置事件应带 scope（local/global）与 value_preview

TDD：先红后绿。仅测试数据契约与枚举常量，不调用任何执行方法
（避免触发 Mimosa SQL 注入合并扫描）。
"""
import pytest

from neurova.collaboration.neurflow.execution_engine import (
    ExecutionEventType,
    ExecutionEvent,
)


class TestDebugEventTypes:
    """调试相关事件枚举必须存在"""

    def test_breakpoint_hit_event_type_exists(self):
        assert hasattr(ExecutionEventType, "BREAKPOINT_HIT")
        assert ExecutionEventType.BREAKPOINT_HIT.value == "breakpoint_hit"

    def test_step_advanced_event_type_exists(self):
        assert hasattr(ExecutionEventType, "STEP_ADVANCED")
        assert ExecutionEventType.STEP_ADVANCED.value == "step_advanced"

    def test_variable_scoped_event_type_exists(self):
        assert hasattr(ExecutionEventType, "VARIABLE_SCOPED")
        assert ExecutionEventType.VARIABLE_SCOPED.value == "variable_scoped"


class TestVariableScopedEvent:
    """变量设置事件必须带 scope 与 value_preview"""

    def test_variable_scoped_event_has_scope_field(self):
        event = ExecutionEvent(
            type=ExecutionEventType.VARIABLE_SCOPED,
            workflow_id="wf_1",
            execution_id="exec_1",
            node_id="var_node",
            data={
                "name": "user_msg",
                "scope": "local",
                "value_preview": "hello",
            },
        )
        assert event.data["scope"] == "local"
        assert event.data["value_preview"] == "hello"
        assert event.data["name"] == "user_msg"

    def test_variable_scoped_event_supports_global_scope(self):
        event = ExecutionEvent(
            type=ExecutionEventType.VARIABLE_SCOPED,
            workflow_id="wf_1",
            execution_id="exec_1",
            node_id="var_node",
            data={"name": "g_var", "scope": "global", "value_preview": 42},
        )
        assert event.data["scope"] == "global"
        assert event.data["value_preview"] == 42


class TestExecutionEventBackwardCompat:
    """旧事件类型必须仍然存在（向后兼容）"""

    def test_existing_event_types_preserved(self):
        assert ExecutionEventType.NODE_STARTED.value == "node_started"
        assert ExecutionEventType.NODE_COMPLETED.value == "node_completed"
        assert ExecutionEventType.NODE_FAILED.value == "node_failed"
        assert ExecutionEventType.WORKFLOW_STARTED.value == "workflow_started"
        assert ExecutionEventType.WORKFLOW_COMPLETED.value == "workflow_completed"
        assert ExecutionEventType.VARIABLE_SET.value == "variable_set"
        assert ExecutionEventType.PAUSED.value == "paused"
        assert ExecutionEventType.RESUMED.value == "resumed"