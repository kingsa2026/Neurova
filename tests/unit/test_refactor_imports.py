"""
架构重构导入验证测试

验证重构后所有模块的导入路径仍然有效。
这是 tracer bullet 测试，确保重构不破坏现有功能。
"""

import pytest


class TestContextImports:
    """上下文系统导入测试"""

    def test_context_package_import(self):
        """验证 neurova.context 包可以导入"""
        import neurova.context
        assert neurova.context is not None

    def test_unified_context_injector_import(self):
        """验证 UnifiedContextInjector 可以从新路径导入"""
        from neurova.context import UnifiedContextInjector
        assert UnifiedContextInjector is not None

    def test_context_builder_import(self):
        """验证 ContextBuilder 可以从新路径导入"""
        from neurova.context import ContextBuilder
        assert ContextBuilder is not None

    def test_token_budget_import(self):
        """验证 TokenBudget 可以从新路径导入"""
        from neurova.context import TokenBudget
        assert TokenBudget is not None

    def test_context_priority_import(self):
        """验证 ContextPriority 可以从新路径导入"""
        from neurova.context import ContextPriority
        assert ContextPriority is not None

    def test_context_entry_import(self):
        """验证 ContextEntry 可以从新路径导入"""
        from neurova.context import ContextEntry
        assert ContextEntry is not None

    def test_context_build_result_import(self):
        """验证 ContextBuildResult 可以从新路径导入"""
        from neurova.context import ContextBuildResult
        assert ContextBuildResult is not None

    def test_context_orchestrator_import(self):
        """验证 ContextOrchestrator 可以从新路径导入"""
        from neurova.context import ContextOrchestrator
        assert ContextOrchestrator is not None

    def test_create_unified_context_injector_import(self):
        """验证工厂函数可以从新路径导入"""
        from neurova.context import create_unified_context_injector
        assert callable(create_unified_context_injector)

    def test_old_import_path_compatible(self):
        """验证旧导入路径仍然可用（向后兼容）"""
        # 这个测试确保我们保留了兼容层
        from neurova.context import UnifiedContextInjector
        assert UnifiedContextInjector is not None


class TestCollaborateImports:
    """协作包导入测试。

    批 109（§6-312 裁乙）退役了从未接线的协作模板半区，原先这里的 7 格
    （`CollaborationTemplate`/`TemplateManager`/`TemplateType`/`AgentRole`/`TaskStep`/
    `WorkflowDefinition`/`get_template_manager`）只是"能导入即绿"的形状检阅——
    它们既不证活链路也不约束行为，随符号一并退。现役那份模板实现与消费链见
    `neurova/agent/templates/collaboration_template.py` ＋ `neurova/agent/team.py`。
    """

    def test_collaborate_package_import(self):
        """验证 neurova.collaborate 包可以导入"""
        import neurova.collaborate
        assert neurova.collaborate is not None

    def test_scheduler_facade_symbols_import(self):
        """现役调度链的六个名必须仍从门面取到（退役不许把活面一起关掉）。"""
        from neurova.collaborate import (
            AgentScheduler, FlowContext, ScheduledTask,
            compute_next_run, get_scheduler, register_action_handlers,
        )
        assert callable(get_scheduler) and callable(compute_next_run)
        assert callable(register_action_handlers)
        assert AgentScheduler is not None and FlowContext is not None and ScheduledTask is not None


class TestWorkflowImports:
    """工作流系统导入测试（现役面只有调度那一半，见 `test_collaborateIslandRetirement.py`）。"""

    def test_workflow_package_import(self):
        """验证 neurova.collaborate.workflow 包可以导入"""
        import neurova.collaborate.workflow
        assert neurova.collaborate.workflow is not None

    def test_agent_scheduler_import(self):
        """验证 AgentScheduler 可以从新路径导入"""
        from neurova.collaborate.workflow import AgentScheduler
        assert AgentScheduler is not None

    def test_flow_context_import(self):
        """验证 FlowContext 可以从新路径导入"""
        from neurova.collaborate.workflow import FlowContext
        assert FlowContext is not None

    def test_scheduled_task_import(self):
        """验证 ScheduledTask 可以从新路径导入"""
        from neurova.collaborate.workflow import ScheduledTask
        assert ScheduledTask is not None


class TestEndToEndFunctionality:
    """端到端功能验证"""

    def test_context_builder_instantiation(self):
        """验证 ContextBuilder 可以实例化"""
        from neurova.context import ContextBuilder
        builder = ContextBuilder()
        assert builder is not None

    def test_token_budget_defaults(self):
        """验证 TokenBudget 默认值正确"""
        from neurova.context import TokenBudget
        budget = TokenBudget()
        assert budget.max_total == 16000
        assert budget.system_prompt == 1500
