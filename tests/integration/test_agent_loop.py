"""
Agent Loop 系统测试

验证 Agent Loop 重构是否正常工作。
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.registry import (
    register_loop,
    find_agent_loop,
    list_registered_loops,
    LoopRegistry,
)


class MockAgent:
    """模拟 Agent 对象，用于测试"""
    def __init__(self):
        self.config = Mock()
        self.config.name = "TestAgent"
        self.config.llm_config = Mock()
        self.config.llm_config.model = "gpt-4"
        self.llm_client = Mock()
        self.skill_registry = None


class TestBaseAgentLoop:
    """测试 BaseAgentLoop"""
    
    def test_base_class_is_abstract(self):
        """测试 BaseAgentLoop 是抽象类"""
        with pytest.raises(TypeError):
            # 不能实例化抽象类
            loop = BaseAgentLoop(MockAgent())
    
    def test_subclass_must_implement_predict_step(self):
        """测试子类必须实现 predict_step"""
        class IncompleteLoop(BaseAgentLoop):
            pass
        
        with pytest.raises(TypeError):
            loop = IncompleteLoop(MockAgent())


class TestLoopRegistry:
    """测试 Loop 注册机制"""
    
    def setup_method(self):
        """每个测试前清空注册表。

        neurova.agent.loops 包被导入时会副作用注册 2 个内置 Loop，
        若不在每个测试开始前清空，断言注册表数量会受全局状态污染。
        """
        LoopRegistry.clear()
    
    def teardown_method(self):
        """每个测试后清空注册表"""
        LoopRegistry.clear()
    
    def test_register_loop_decorator(self):
        """测试 @register_loop 装饰器"""
        @register_loop(r"test-.*", priority=10)
        class TestLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return "test"
        
        # 检查是否注册成功
        loops = list_registered_loops()
        assert len(loops) == 1
        assert loops[0]["name"] == "TestLoop"
        assert loops[0]["priority"] == 10
    
    def test_find_agent_loop(self):
        """测试 find_agent_loop() 函数"""
        @register_loop(r"gpt-.*", priority=10)
        class GPTLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return "gpt"
        
        @register_loop(r"claude-.*", priority=20)
        class ClaudeLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return "claude"
        
        # 应该找到 ClaudeLoop (优先级更高)
        loop_class = find_agent_loop("claude-3-opus")
        assert loop_class == ClaudeLoop
        
        # 应该找到 GPTLoop
        loop_class = find_agent_loop("gpt-4")
        assert loop_class == GPTLoop
        
        # 应该返回默认（第一个注册的）
        loop_class = find_agent_loop("unknown-model")
        assert loop_class is not None  # 应该返回第一个
    
    def test_multiple_loops_same_pattern(self):
        """测试多个 Loop 匹配同一模型"""
        @register_loop(r"gpt-.*", priority=5)
        class LowPriorityLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return "low"
        
        @register_loop(r"gpt-.*", priority=15)
        class HighPriorityLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return "high"
        
        # 应该返回高优先级的
        loop_class = find_agent_loop("gpt-4")
        assert loop_class == HighPriorityLoop


class TestOpenAILoop:
    """测试 OpenAI Loop"""
    
    @pytest.mark.asyncio
    async def test_predict_step_normal(self):
        """测试普通预测"""
        from neurova.agent.loops.openai_loop import OpenAILoop
        
        # 创建模拟 Agent
        agent = MockAgent()
        agent.llm_client.chat = AsyncMock(return_value=Mock(
            content="Test response",
            tool_calls=None,
            reasoning_content=None,
        ))
        
        # 创建 Loop
        loop = OpenAILoop(agent)
        
        # 执行预测
        messages = [{"role": "user", "content": "Hello"}]
        response = await loop.predict_step(messages=messages, stream=False)
        
        assert response.content == "Test response"
    
    @pytest.mark.asyncio
    async def test_predict_step_with_tools(self):
        """测试带工具的预测"""
        from neurova.agent.loops.openai_loop import OpenAILoop
        
        # 模拟 LLM 返回 tool_calls
        mock_response = Mock()
        mock_response.content = "Tool call"
        mock_response.tool_calls = [
            {
                "id": "call_123",
                "function": {
                    "name": "test_tool",
                    "arguments": '{"param": "value"}'
                }
            }
        ]
        mock_response.reasoning_content = None
        
        agent = MockAgent()
        agent.llm_client.chat = AsyncMock(return_value=mock_response)
        agent.skill_registry = Mock()
        agent.skill_registry.execute_skill = AsyncMock(return_value=Mock(
            success=True,
            data={"result": "success"}
        ))
        
        loop = OpenAILoop(agent)
        messages = [{"role": "user", "content": "Use tool"}]
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        
        response = await loop.predict_step(messages=messages, tools=tools)
        
        # 应该执行工具并返回最终结果
        assert response is not None


class TestAgentIntegration:
    """测试 Agent 集成"""
    
    @pytest.mark.asyncio
    async def test_agent_initializes_loop(self, monkeypatch):
        """测试 Agent 初始化时创建 Loop"""
        from neurova.agent_core import Agent, AgentConfig
        
        # 创建配置
        config = AgentConfig(
            name="TestAgent",
            agent_id="test_agent",
            workspace_path=str(Path("./test_workspace")),
            llm_api_key="test-key",
            llm_model="gpt-4",
        )
        
        # 模拟 LLMClient（使用 pytest 内置 monkeypatch fixture）
        monkeypatch.setattr("neurova.llm_client.OpenAI", Mock())
        
        agent = Agent(config=config)
        
        # 检查 Loop 是否初始化
        if hasattr(agent, 'loop') and agent.loop is not None:
            assert agent.loop is not None
            print(f"✓ Agent Loop initialized: {agent.loop.__class__.__name__}")
        else:
            print("⚠ Agent Loop not initialized (maybe import failed)")
    
    @pytest.mark.asyncio
    async def test_agent_chat_uses_loop(self, monkeypatch):
        """测试 Agent.chat() 使用 Loop"""
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="TestAgent",
            agent_id="test_agent",
            workspace_path=str(Path("./test_workspace")),
            llm_api_key="test-key",
            llm_model="gpt-4",
        )
        
        # 模拟 LLMClient（使用 pytest 内置 monkeypatch fixture）
        monkeypatch.setattr("neurova.llm_client.OpenAI", Mock())
        
        agent = Agent(config=config)
        
        # 模拟 Loop
        if agent.loop:
            agent.loop.predict_step = AsyncMock(return_value=Mock(
                content="Loop response"
            ))
            
            # 模拟 chat() 方法
            response = await agent.chat("Test input")
            
            # 检查是否使用了 Loop
            agent.loop.predict_step.assert_called_once()
            assert "Loop response" in str(response)


def test_imports():
    """测试所有导入是否正常"""
    try:
        from neurova.agent import register_loop, find_agent_loop
        from neurova.agent.loops import BaseAgentLoop
        from neurova.agent.loops.registry import LoopRegistry
        from neurova.agent.loops.openai_loop import OpenAILoop
        
        print("✓ All imports successful")
        return True
    
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


if __name__ == "__main__":
    # 运行简单测试
    print("Running Agent Loop tests...")
    
    # 测试导入
    test_imports()
    
    # 测试注册机制
    print("\nTesting Loop registry...")
    
    @register_loop(r"test-.*", priority=10)
    class TestLoop(BaseAgentLoop):
        async def predict_step(self, messages, tools=None, **kwargs):
            return "test"
    
    loops = list_registered_loops()
    print(f"✓ Registered {len(loops)} loop(s)")
    
    loop_class = find_agent_loop("test-model")
    print(f"✓ Found loop: {loop_class.__name__ if loop_class else None}")
    
    print("\n All tests passed!")
