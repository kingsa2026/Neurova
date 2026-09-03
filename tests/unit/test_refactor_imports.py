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
    """协作系统导入测试"""

    def test_collaborate_package_import(self):
        """验证 neurova.collaborate 包可以导入"""
        import neurova.collaborate
        assert neurova.collaborate is not None

    def test_collaboration_template_import(self):
        """验证 CollaborationTemplate 可以从新路径导入"""
        from neurova.collaborate import CollaborationTemplate
        assert CollaborationTemplate is not None

    def test_template_manager_import(self):
        """验证 TemplateManager 可以从新路径导入"""
        from neurova.collaborate import TemplateManager
        assert TemplateManager is not None

    def test_template_type_import(self):
        """验证 TemplateType 可以从新路径导入"""
        from neurova.collaborate import TemplateType
        assert TemplateType is not None

    def test_agent_role_import(self):
        """验证 AgentRole 可以从新路径导入"""
        from neurova.collaborate import AgentRole
        assert AgentRole is not None

    def test_task_step_import(self):
        """验证 TaskStep 可以从新路径导入"""
        from neurova.collaborate import TaskStep
        assert TaskStep is not None

    def test_workflow_definition_import(self):
        """验证 WorkflowDefinition 可以从新路径导入"""
        from neurova.collaborate import WorkflowDefinition
        assert WorkflowDefinition is not None

    def test_get_template_manager_import(self):
        """验证 get_template_manager 可以从新路径导入"""
        from neurova.collaborate import get_template_manager
        assert callable(get_template_manager)


class TestWorkflowImports:
    """工作流系统导入测试"""

    def test_workflow_package_import(self):
        """验证 neurova.collaborate.workflow 包可以导入"""
        import neurova.collaborate.workflow
        assert neurova.collaborate.workflow is not None

    def test_flow_orchestrator_import(self):
        """验证 FlowOrchestrator 可以从新路径导入"""
        from neurova.collaborate.workflow import FlowOrchestrator
        assert FlowOrchestrator is not None

    def test_agent_scheduler_import(self):
        """验证 AgentScheduler 可以从新路径导入"""
        from neurova.collaborate.workflow import AgentScheduler
        assert AgentScheduler is not None

    def test_flow_phase_import(self):
        """验证 FlowPhase 可以从新路径导入"""
        from neurova.collaborate.workflow import FlowPhase
        assert FlowPhase is not None

    def test_flow_event_import(self):
        """验证 FlowEvent 可以从新路径导入"""
        from neurova.collaborate.workflow import FlowEvent
        assert FlowEvent is not None

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

    def test_template_type_enum_values(self):
        """验证 TemplateType 枚举值"""
        from neurova.collaborate import TemplateType
        assert TemplateType.CODE_REVIEW.value == "code_review"
        assert TemplateType.PAIR_PROGRAMMING.value == "pair_programming"

    def test_flow_phase_enum_values(self):
        """验证 FlowPhase 枚举值"""
        from neurova.collaborate.workflow import FlowPhase
        assert FlowPhase.IDLE.value == "idle"
        assert FlowPhase.CONVERSATION.value == "conversation"
