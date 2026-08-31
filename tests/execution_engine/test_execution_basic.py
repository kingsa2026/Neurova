#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple test script to verify execution_engine modules work correctly.
"""

import asyncio
import sys

def test_imports():
    """Test all imports."""
    print("Testing imports...")
    
    try:
        from neurova.execution_engine.plan_orchestrator import (
            StepStatus,
            ExecutionStep,
            ExecutionPlan,
            PlanOrchestrator,
            get_plan_orchestrator,
            reset_plan_orchestrator,
        )
        print("✓ plan_orchestrator imports successful")
    except Exception as e:
        print(f"✗ plan_orchestrator import failed: {e}")
        return False
    
    try:
        from neurova.execution_engine.mcp_manager import (
            MCPServerConfig,
            MCPTool,
            MCPManager,
            get_mcp_manager,
            reset_mcp_manager,
        )
        print("✓ mcp_manager imports successful")
    except Exception as e:
        print(f"✗ mcp_manager import failed: {e}")
        return False
    
    try:
        from neurova.execution_engine.tool_engine import ToolEngine
        print("✓ tool_engine import successful")
    except Exception as e:
        print(f"✗ tool_engine import failed: {e}")
        return False
    
    try:
        from neurova.execution_engine.workflow_engine import WorkflowEngine
        print("✓ workflow_engine import successful")
    except Exception as e:
        print(f"✗ workflow_engine import failed: {e}")
        return False
    
    return True


def test_dataclasses():
    """Test dataclass creation."""
    print("\nTesting dataclasses...")
    
    try:
        from neurova.execution_engine.plan_orchestrator import (
            StepStatus,
            ExecutionStep,
            ExecutionPlan,
        )
        
        # Test ExecutionStep
        step = ExecutionStep(
            step_id="test_001",
            name="Test Step",
            action="test_action",
        )
        print(f"✓ ExecutionStep created: {step.step_id}")
        
        # Test ExecutionPlan
        plan = ExecutionPlan(
            plan_id="plan_001",
            goal="Test Goal",
            steps=[step],
        )
        print(f"✓ ExecutionPlan created: {plan.plan_id}, steps={len(plan.steps)}")
        
    except Exception as e:
        print(f"✗ Dataclass test failed: {e}")
        return False
    
    try:
        from neurova.execution_engine.mcp_manager import MCPServerConfig, MCPTool
        
        # Test MCPServerConfig
        config = MCPServerConfig(
            server_id="server_001",
            name="Test Server",
            transport_type="stdio",
            command="python",
        )
        print(f"✓ MCPServerConfig created: {config.server_id}")
        
        # Test MCPTool
        tool = MCPTool(
            name="test_tool",
            description="Test tool",
            server_id="server_001",
        )
        print(f"✓ MCPTool created: {tool.name}")
        
    except Exception as e:
        print(f"✗ MCP dataclass test failed: {e}")
        return False
    
    return True


async def test_plan_orchestrator():
    """Test PlanOrchestrator basic functionality."""
    print("\nTesting PlanOrchestrator...")
    
    try:
        from neurova.execution_engine.plan_orchestrator import (
            PlanOrchestrator,
            get_plan_orchestrator,
            reset_plan_orchestrator,
        )
        
        # Reset and get instance
        reset_plan_orchestrator()
        orchestrator = get_plan_orchestrator()
        print(f"✓ PlanOrchestrator instance created")
        
        # Test create_plan
        plan = await orchestrator.create_plan("Test task")
        print(f"✓ Plan created: {plan.plan_id}, steps={len(plan.steps)}")
        
        # Test get_plan
        retrieved = orchestrator.get_plan(plan.plan_id)
        assert retrieved is not None
        print(f"✓ Plan retrieved: {retrieved.plan_id}")
        
        # Test get_all_plans
        all_plans = orchestrator.get_all_plans()
        assert len(all_plans) >= 1
        print(f"✓ All plans retrieved: {len(all_plans)} plans")
        
        # Clean up
        reset_plan_orchestrator()
        print(f"✓ PlanOrchestrator reset successful")
        
    except Exception as e:
        print(f"✗ PlanOrchestrator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True



async def main():
    """Run all tests."""
    print("=" * 60)
    print("Execution Engine Basic Functionality Tests")
    print("=" * 60)
    
    # Test imports
    if not test_imports():
        print("\n❌ Import tests failed!")
        return 1
    
    # Test dataclasses
    if not test_dataclasses():
        print("\n❌ Dataclass tests failed!")
        return 1
    
    # Test PlanOrchestrator
    if not await test_plan_orchestrator():
        print("\n❌ PlanOrchestrator tests failed!")
        return 1
    
    # Test MCPManager
    if not await test_mcp_manager():
        print("\n❌ MCPManager tests failed!")
        return 1
    
    print("\n" + "=" * 60)
    print("✅ All basic tests passed!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
