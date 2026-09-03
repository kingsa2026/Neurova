"""
Agent核心模块单元测试

测试Agent类的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.agent_core import Agent, AgentConfig, AgentLLMClient


class TestAgentConfig:
    """AgentConfig测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = AgentConfig(
            name="test_agent",
            agent_id="test_001",
            workspace_path="/tmp/test_workspace"
        )
        assert config.name == "test_agent"
        assert config.agent_id == "test_001"
    
    def test_config_requires_workspace_path(self):
        """测试配置需要workspace_path"""
        with pytest.raises(ValueError):
            AgentConfig(name="test", agent_id="test")


class TestAgentLLMClient:
    """AgentLLMClient测试"""
    
    def test_init(self):
        """测试初始化"""
        client = AgentLLMClient(model="gpt-4", provider_id="openai")
        assert client.model == "gpt-4"
        assert client.provider_id == "openai"
    
    def test_default_model(self):
        """测试默认模型"""
        client = AgentLLMClient()
        assert client.model == "auto"


class TestAgent:
    """Agent类测试"""
    
    def test_agent_init(self):
        """测试Agent初始化"""
        with patch('neurova.agent_core.SubSystemContainer') as mock_container:
            mock_container.return_value.init_all = Mock()
            
            config = AgentConfig(
                name="test_agent",
                agent_id="test_001",
                workspace_path="/tmp/test_workspace"
            )
            
            agent = Agent(config=config)
            assert agent.config.name == "test_agent"
    
    def test_agent_repr(self):
        """测试Agent字符串表示"""
        with patch('neurova.agent_core.SubSystemContainer') as mock_container:
            mock_container.return_value.init_all = Mock()
            
            config = AgentConfig(
                name="test_agent",
                agent_id="test_001",
                workspace_path="/tmp/test_workspace"
            )
            
            agent = Agent(config=config)
            assert "test_agent" in repr(agent)
            assert "test_001" in repr(agent)
