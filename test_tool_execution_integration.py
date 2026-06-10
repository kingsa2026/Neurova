#!/usr/bin/env python3
"""测试 ToolExecutionManager 集成到 ChatPipeline"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock

# 模拟 Agent 类
class MockAgent:
    def __init__(self):
        self.config = Mock()
        self.memory_agent = Mock()
        self.context_orchestrator = Mock()
        self.tool_memory = Mock()
        self.skill_manager = Mock()
        self.tool_synthesizer = Mock()
        self.unified_retriever = Mock()
        self.crystallizer = Mock()
        self.trace_manager = Mock()
        self.neuHebb_manager = Mock()
        self.loop = Mock()
        self.llm_client = Mock()
        self.tool_executor = Mock()
        self.post_chat_pipeline = Mock()
        self.idle_tracker = Mock()

# 模拟工具执行器
class MockToolExecutor:
    async def execute_tool(self, tool_name, params, user_input):
        """模拟执行工具"""
        await asyncio.sleep(0.1)  # 模拟执行时间
        return {
            "status": "success",
            "result": f"Executed {tool_name} successfully",
            "tool_name": tool_name,
        }
    
    async def execute_from_memory_async(self, memory_result, user_input):
        """模拟从内存执行工具"""
        tool_name = memory_result.get('tool_name')
        params = memory_result.get('params', {})
        return await self.execute_tool(tool_name, params, user_input)

async def test_tool_execution_manager_integration():
    """测试 ToolExecutionManager 集成"""
    from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
    from neurova.agent.tool_execution_manager import ToolExecutionManager, TimeoutStrategy, ExecutionStatus
    
    # 创建模拟 Agent
    mock_agent = MockAgent()
    mock_agent.tool_executor = MockToolExecutor()
    
    # 创建 ChatPipeline
    pipeline = ChatPipeline(mock_agent)
    
    # 验证 ToolExecutionManager 已初始化
    assert hasattr(pipeline, '_tool_execution_manager')
    assert isinstance(pipeline._tool_execution_manager, ToolExecutionManager)
    assert pipeline.tool_execution_manager is pipeline._tool_execution_manager
    
    print("✓ ToolExecutionManager 已正确初始化")
    
    # 创建测试上下文
    ctx = ChatContext(
        user_input="测试用户输入",
        tool_memory_result={
            "tool_name": "test_tool",
            "params": {"query": "test"},
            "confidence": 0.8,
        },
    )
    
    # 测试工具执行
    await pipeline._auto_execute_tool(ctx)
    
    # 验证执行结果
    assert ctx.tool_decision == "auto_executed", f"Expected 'auto_executed', got '{ctx.tool_decision}'"
    assert ctx.auto_execute_result is not None
    assert ctx.auto_execute_result.get("status") == "success"
    
    print("✓ 工具自动执行成功")
    
    # 测试低置信度场景
    ctx2 = ChatContext(
        user_input="测试低置信度",
        tool_memory_result={
            "tool_name": "low_confidence_tool",
            "params": {},
            "confidence": 0.5,
        },
    )
    
    await pipeline._auto_execute_tool(ctx2)
    assert ctx2.tool_decision == "suggest", f"Expected 'suggest', got '{ctx2.tool_decision}'"
    
    print("✓ 低置信度工具正确转为建议模式")
    
    # 测试超时场景
    class SlowToolExecutor:
        async def execute_tool(self, tool_name, params, user_input):
            await asyncio.sleep(10.0)  # 模拟慢速执行
            return {"status": "success"}
        
        async def execute_from_memory_async(self, memory_result, user_input):
            tool_name = memory_result.get('tool_name')
            params = memory_result.get('params', {})
            return await self.execute_tool(tool_name, params, user_input)
    
    mock_agent.tool_executor = SlowToolExecutor()
    
    ctx3 = ChatContext(
        user_input="测试超时",
        tool_memory_result={
            "tool_name": "slow_tool",
            "params": {},
            "confidence": 0.9,
        },
    )
    
    # 使用较短的超时时间进行测试
    pipeline._tool_execution_manager._contexts.clear()  # 清理之前的上下文
    
    # 修改 execute 方法使用更短的超时时间
    original_execute = pipeline._tool_execution_manager.execute
    
    async def short_timeout_execute(*args, **kwargs):
        kwargs['timeout'] = 0.1  # 100ms 超时
        return await original_execute(*args, **kwargs)
    
    pipeline._tool_execution_manager.execute = short_timeout_execute
    
    await pipeline._auto_execute_tool(ctx3)
    assert ctx3.tool_decision == "timeout", f"Expected 'timeout', got '{ctx3.tool_decision}'"
    
    print("✓ 超时场景正确处理")
    
    print("\n🎉 所有集成测试通过！")

if __name__ == "__main__":
    asyncio.run(test_tool_execution_manager_integration())