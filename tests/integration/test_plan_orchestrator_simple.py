# -*- coding: utf-8 -*-
"""
Simplified tests for PlanOrchestrator - matches implementation
"""

import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from neurova.execution_engine.plan_orchestrator import (
    StepStatus,
    ExecutionStep,
    ExecutionPlan,
    PlanOrchestrator,
    get_plan_orchestrator,
    reset_plan_orchestrator,
)


class TestExecutionStep:
    """Test ExecutionStep dataclass."""

    def test_create_execution_step_minimal(self):
        """Test creating ExecutionStep with minimal parameters."""
        step = ExecutionStep(
            step_id="step_001",
            name="Test Step",
            action="test_action",
        )
        
        assert step.step_id == "step_001"
        assert step.name == "Test Step"
        assert step.action == "test_action"
        assert step.description == ""
        assert step.inputs == {}
        assert step.outputs == {}
        assert step.dependencies == []
        assert step.status == StepStatus.PENDING
        assert step.retry_count == 0
        assert step.max_retries == 3
        assert step.timeout == 300
        assert step.metadata == {}

    def test_create_execution_step_full(self):
        """Test creating ExecutionStep with all parameters."""
        step = ExecutionStep(
            step_id="step_002",
            name="Full Step",
            action="complex_action",
            description="A complex test step",
            inputs={"param1": "value1", "param2": 42},
            outputs={"result": None},
            dependencies=["step_001"],
            status=StepStatus.RUNNING,
            retry_count=1,
            max_retries=5,
            timeout=600,
            metadata={"priority": "high"},
        )
        
        assert step.step_id == "step_002"
        assert step.description == "A complex test step"
        assert step.inputs == {"param1": "value1", "param2": 42}
        assert step.outputs == {"result": None}
        assert step.dependencies == ["step_001"]
        assert step.status == StepStatus.RUNNING
        assert step.retry_count == 1
        assert step.max_retries == 5
        assert step.timeout == 600
        assert step.metadata == {"priority": "high"}

    def test_execution_step_to_dict(self):
        """Test converting ExecutionStep to dictionary."""
        step = ExecutionStep(
            step_id="step_001",
            name="Test Step",
            action="test_action",
            inputs={"input": "value"},
            metadata={"key": "value"},
        )
        
        result = step.to_dict()
        
        assert result["step_id"] == "step_001"
        assert result["name"] == "Test Step"
        assert result["action"] == "test_action"
        assert result["status"] == "pending"
        assert result["inputs"] == {"input": "value"}
        assert result["metadata"] == {"key": "value"}


class TestPlanOrchestrator:
    """Test PlanOrchestrator class."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset singleton before and after each test."""
        reset_plan_orchestrator()
        yield
        reset_plan_orchestrator()

    def test_initialization(self):
        """Test PlanOrchestrator initialization."""
        orchestrator = PlanOrchestrator()
        assert orchestrator is not None
        assert hasattr(orchestrator, 'plans')
        assert hasattr(orchestrator, 'max_concurrent_steps')

    @pytest.mark.asyncio
    async def test_create_plan(self):
        """Test creating a plan."""
        orchestrator = PlanOrchestrator()
        plan = await orchestrator.create_plan("Test task")
        
        assert plan is not None
        assert plan.plan_id != ""
        assert plan.goal == "Test task"
        assert len(plan.steps) >= 1

    @pytest.mark.asyncio
    async def test_get_plan(self):
        """Test getting a plan."""
        orchestrator = PlanOrchestrator()
        plan = await orchestrator.create_plan("Test task")
        
        retrieved = orchestrator.get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id

    @pytest.mark.asyncio
    async def test_execute_step(self):
        """Test executing a step."""
        orchestrator = PlanOrchestrator()
        step = ExecutionStep(
            step_id="step_001",
            name="Test Step",
            action="test_action",
        )
        
        result = await orchestrator._execute_step(step)
        
        assert result is not None
        assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
