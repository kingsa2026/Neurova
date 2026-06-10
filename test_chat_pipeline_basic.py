#!/usr/bin/env python3
"""测试 ChatPipeline 基本功能"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from unittest.mock import Mock, AsyncMock

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

async def test_chat_pipeline_basic():
    """测试 ChatPipeline 基本功能"""
    from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
    from neurova.agent.tool_execution_manager import ToolExecutionManager
    
    # 创建模拟 Agent
    mock_agent = MockAgent()
    
    # 创建 ChatPipeline
    pipeline = ChatPipeline(mock_agent)
    
    # 验证基本属性
    assert pipeline._agent is mock_agent
    assert isinstance(pipeline._tool_execution_manager, ToolExecutionManager)
    assert pipeline.tool_execution_manager is pipeline._tool_execution_manager
    
    print("✓ ChatPipeline 初始化正确")
    
    # 验证属性代理
    assert pipeline.config is mock_agent.config
    assert pipeline.memory_agent is mock_agent.memory_agent
    assert pipeline.context_orchestrator is mock_agent.context_orchestrator
    assert pipeline.tool_memory is mock_agent.tool_memory
    assert pipeline.skill_manager is mock_agent.skill_manager
    assert pipeline.tool_synthesizer is mock_agent.tool_synthesizer
    assert pipeline.unified_retriever is mock_agent.unified_retriever
    assert pipeline.crystallizer is mock_agent.crystallizer
    assert pipeline.trace_manager is mock_agent.trace_manager
    assert pipeline.neuHebb_manager is mock_agent.neuHebb_manager
    assert pipeline.loop is mock_agent.loop
    assert pipeline.llm_client is mock_agent.llm_client
    assert pipeline.tool_executor is mock_agent.tool_executor
    assert pipeline.post_chat_pipeline is mock_agent.post_chat_pipeline
    assert pipeline.idle_tracker is mock_agent.idle_tracker
    
    print("✓ 所有属性代理正确")
    
    # 测试 ChatContext 创建
    ctx = ChatContext(user_input="测试输入")
    assert ctx.user_input == "测试输入"
    assert ctx.stream is False
    assert ctx.save_memory is True
    assert ctx.tool_memory_result is None
    assert ctx.tool_decision == "do_not_execute"
    
    print("✓ ChatContext 创建正确")
    
    # 测试 ToolExecutionManager 功能
    manager = pipeline.tool_execution_manager
    assert manager.get_health()["total_contexts"] == 0
    
    print("✓ ToolExecutionManager 功能正常")
    
    print("\n🎉 ChatPipeline 基本功能测试通过！")

if __name__ == "__main__":
    asyncio.run(test_chat_pipeline_basic())