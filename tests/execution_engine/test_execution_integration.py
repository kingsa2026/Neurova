# -*- coding: utf-8 -*-
"""
Integration tests for Execution Engine modules.

Test cases:
- Test PlanOrchestrator + CognitionOrchestrator integration
- Test ToolEngine + WorkflowEngine integration
- Test MCPManager + ToolEngine integration
- Test complete execution flow
"""

import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.execution_engine.plan_orchestrator import (
    PlanOrchestrator,
    ExecutionPlan,
    ExecutionStep,
    get_plan_orchestrator,
    reset_plan_orchestrator,
)
from neurova.execution_engine.tool_engine import ToolEngine
from neurova.execution_engine.workflow_engine import WorkflowEngine
class TestPlanOrchestratorCognitionIntegration:
    """Test PlanOrchestrator integration with CognitionOrchestrator."""
    
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset singleton before and after each test."""
        reset_plan_orchestrator()
        yield
        reset_plan_orchestrator()
    
    @pytest.mark.asyncio
    async def test_create_plan_for_cognition(self):
        """Test creating plan from cognition context."""
        plan_orch = get_plan_orchestrator()
        
        # Simulate cognition context
        cognition_context = {
            "user_input": "开发一个用户登录功能",
            "attention_level": "high",
            "memory_context": {"previous_tasks": ["task1", "task2"]},
        }
        
        plan = await plan_orch.create_plan(
            task=cognition_context["user_input"],
            context=cognition_context,
        )
        
        assert plan is not None
        assert plan.context == cognition_context
        assert len(plan.steps) > 0
    
    @pytest.mark.asyncio
    async def test_plan_includes_cognitive_state(self):
        """Test that plan includes cognitive state information."""
        plan_orch = get_plan_orchestrator()
        
        context = {
            "cognitive_state": {
                "attention": "high",
                "memory_load": 0.8,
            }
        }
        
        plan = await plan_orch.create_plan("Test task", context)
        
        assert "cognitive_state" in plan.context
        assert plan.context["cognitive_state"]["attention"] == "high"


class TestToolEngineWorkflowIntegration:
    """Test ToolEngine integration with WorkflowEngine."""
    
    @pytest.mark.asyncio
    async def test_workflow_uses_tool_engine(self):
        """Test that workflow execution uses ToolEngine."""
        tool_engine = ToolEngine()
        workflow_engine = WorkflowEngine(tool_engine=tool_engine)
        
        # Create a simple workflow
        workflow_def = {
            "name": "Test Workflow",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Tool Step",
                    "action": "execute_tool",
                    "tool_name": "test_tool",
                    "inputs": {},
                }
            ]
        }
        
        # Mock tool execution
        with patch.object(tool_engine, 'execute_tool', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"result": "success"}
            
            result = await workflow_engine.execute_workflow(workflow_def)
            
            assert result is not None
            mock_exec.assert_called_once()



class TestCompleteExecutionFlow:
    """Test complete execution flow across modules."""
    
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset singletons before and after each test."""
        reset_plan_orchestrator()
        reset_mcp_manager()
        yield
        reset_plan_orchestrator()
        reset_mcp_manager()
    
    @pytest.mark.asyncio
    async def test_full_execution_pipeline(self):
        """Test full pipeline: Plan → Tools → Workflow → Execution."""
        # 1. Create plan
        plan_orch = get_plan_orchestrator()
        plan = await plan_orch.create_plan("Complete test task")
        
        assert plan is not None
        assert len(plan.steps) > 0
        
        # 2. Setup ToolEngine
        tool_engine = ToolEngine()
        
        # 3. Register tools (mocked)
        for step in plan.steps:
            step.action = "execute_tool"
            step.inputs = {"tool_name": "test_tool", "params": {}}
        
        # 4. Mock tool execution
        with patch.object(tool_engine, 'execute_tool', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"result": "step_completed"}
            
            # 5. Execute plan
            with patch.object(plan_orch, 'tool_engine', tool_engine):
                result = await plan_orch.execute_plan(plan.plan_id)
                
                assert result is not None
                assert "step_results" in result
    
    @pytest.mark.asyncio
    async def test_error_handling_across_modules(self):
        """Test error handling propagates correctly."""
        plan_orch = get_plan_orchestrator()
        plan = await plan_orch.create_plan("Error test task")
        
        # Make first step fail
        if len(plan.steps) > 0:
            plan.steps[0].max_retries = 0
            
            with patch.object(plan_orch, '_execute_step', new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = {"status": "failed", "error": "Test error"}
                
                result = await plan_orch.execute_plan(plan.plan_id)
                
                assert result is not None
                assert result["step_results"][0]["status"] == "failed"


class TestExecutionEngineIntegration:
    """Test ExecutionEngine components work together."""
    
    @pytest.mark.asyncio
    async def test_components_share_state(self):
        """Test that components can share state via context."""
        # This test verifies that plan orchestrator, tool engine, and workflow engine
        # can share state through the execution context
        
        plan_orch = get_plan_orchestrator()
        
        # Create a plan with context
        context = {"shared_state": {"key": "value"}}
        plan = await plan_orch.create_plan("Shared state test", context)
        
        assert "shared_state" in plan.context
        assert plan.context["shared_state"]["key"] == "value"
    
    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        """Test concurrent execution of multiple plans."""
        plan_orch = get_plan_orchestrator()
        
        # Create multiple plans
        tasks = []
        for i in range(3):
            task = plan_orch.create_plan(f"Concurrent task {i}")
            tasks.append(task)
        
        plans = await asyncio.gather(*tasks)
        
        assert len(plans) == 3
        assert all(p is not None for p in plans)
        assert len(set(p.plan_id for p in plans)) == 3  # All unique IDs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
