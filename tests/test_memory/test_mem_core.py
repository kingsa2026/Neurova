"""
MemCore 深度模块测试

测试目标：
1. MemCore 封装所有认知层模块
2. Agent 只需导入 MemCore 一个模块
3. 测试更容易 mock（只需 mock MemCore）
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, List, Optional

# 导入被测试模块
from neurova.mem_core import MemCore


class TestMemCoreInitialization:
    """MemCore 初始化测试"""

    def test_mem_core_creation(self):
        """测试 MemCore 可以正常创建"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert mem_core is not None
        assert mem_core._agent == mock_agent

    def test_mem_core_has_required_properties(self):
        """测试 MemCore 有所有必需的属性"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'config')
        assert hasattr(mem_core, 'memory_manager')
        assert hasattr(mem_core, 'storage')
        assert hasattr(mem_core, 'temperature_engine')
        assert hasattr(mem_core, 'recall_engine')
        assert hasattr(mem_core, 'working_memory')
        assert hasattr(mem_core, 'conversation_buffer')
        assert hasattr(mem_core, 'buffer_module')

    def test_mem_core_properties_proxy_to_agent(self):
        """测试 MemCore 属性代理到 Agent"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.memory_manager = Mock()
        mock_agent.storage = Mock()
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert mem_core.memory_manager == mock_agent.memory_manager
        assert mem_core.storage == mock_agent.storage

    def test_mem_core_properties_setter_proxy_to_agent(self):
        """测试 MemCore 属性设置代理到 Agent"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.memory_manager = None
        
        # 执行
        mem_core = MemCore(mock_agent)
        mem_core.memory_manager = Mock()
        
        # 验证
        assert mock_agent.memory_manager == mem_core.memory_manager


class TestMemCoreMemoryModules:
    """MemCore 记忆模块初始化测试"""

    def test_init_memory_modules(self):
        """测试 init_memory_modules 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.enable_memory = True
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'init_memory_modules')
        assert callable(mem_core.init_memory_modules)

    @patch('neurova.cognitive_layers.memory_layer.tool_memory_integration.ToolMemoryIntegration')
    @patch('neurova.cognitive_layers.memory_layer.muscle_memory.MuscleMemory')
    @patch('neurova.cognitive_layers.meta_cognition_layer.question_queue.QuestionQueueManager')
    @patch('neurova.cognitive_layers.meta_cognition_layer.growth_log.GrowthLogManager')
    @patch('neurova.cognitive_layers.memory_layer.attachment_manager.AttachmentManager')
    @patch('neurova.cognitive_layers.memory_layer.modules.buffer_module.BufferModule')
    @patch('neurova.cognitive_layers.memory_layer.conversation_buffer.ConversationMemoryBuffer')
    @patch('neurova.cognitive_layers.memory_layer.working_memory.WorkingMemoryAugmenter')
    @patch('neurova.cognitive_layers.memory_layer.neurova_recall.NeurovaRecallEngine')
    @patch('neurova.cognitive_layers.memory_layer.temperature.TemperatureEngine')
    @patch('neurova.cognitive_layers.memory_layer.manager.MemoryManager')
    def test_init_memory_modules_creates_memory_manager(self, mock_mm_class, *args):
        """测试 init_memory_modules 创建 MemoryManager"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.name = "test_agent"
        mock_agent.config.enable_memory = True
        mock_agent.config.db_path = "/tmp/test.db"
        mock_agent.config.workspace_path = "/tmp/workspace"
        mock_agent.config.attachment_dir = "/tmp/attachments"

        mock_memory_manager = Mock()
        mock_memory_manager.storage = Mock()
        mock_mm_class.return_value = mock_memory_manager

        # 执行
        mem_core = MemCore(mock_agent)
        mem_core.init_memory_modules()

        # 验证
        assert mem_core.memory_manager == mock_memory_manager
        mock_mm_class.assert_called_once()

    @patch('neurova.cognitive_layers.memory_layer.tool_memory_integration.ToolMemoryIntegration')
    @patch('neurova.cognitive_layers.memory_layer.muscle_memory.MuscleMemory')
    @patch('neurova.cognitive_layers.meta_cognition_layer.question_queue.QuestionQueueManager')
    @patch('neurova.cognitive_layers.meta_cognition_layer.growth_log.GrowthLogManager')
    @patch('neurova.cognitive_layers.memory_layer.attachment_manager.AttachmentManager')
    @patch('neurova.cognitive_layers.memory_layer.modules.buffer_module.BufferModule')
    @patch('neurova.cognitive_layers.memory_layer.conversation_buffer.ConversationMemoryBuffer')
    @patch('neurova.cognitive_layers.memory_layer.working_memory.WorkingMemoryAugmenter')
    @patch('neurova.cognitive_layers.memory_layer.neurova_recall.NeurovaRecallEngine')
    @patch('neurova.cognitive_layers.memory_layer.temperature.TemperatureEngine')
    @patch('neurova.cognitive_layers.memory_layer.manager.MemoryManager')
    def test_init_memory_modules_creates_storage(self, mock_mm_class, *args):
        """测试 init_memory_modules 创建 MemoryStorage"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.name = "test_agent"
        mock_agent.config.enable_memory = True
        mock_agent.config.db_path = "/tmp/test.db"
        mock_agent.config.workspace_path = "/tmp/workspace"
        mock_agent.config.attachment_dir = "/tmp/attachments"

        mock_memory_manager = Mock()
        mock_storage = Mock()
        mock_memory_manager.storage = mock_storage
        mock_mm_class.return_value = mock_memory_manager

        # 执行
        mem_core = MemCore(mock_agent)
        mem_core.init_memory_modules()

        # 验证
        assert mem_core.storage == mock_storage


class TestMemCoreMemoryOperations:
    """MemCore 记忆操作测试"""

    def test_retrieve_memories(self):
        """测试 retrieve_memories 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'retrieve_memories')
        assert callable(mem_core.retrieve_memories)

    def test_save_conversation_memory(self):
        """测试 save_conversation_memory 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'save_conversation_memory')
        assert callable(mem_core.save_conversation_memory)

    def test_update_memory_temperature(self):
        """测试 update_memory_temperature 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'update_memory_temperature')
        assert callable(mem_core.update_memory_temperature)

    def test_get_memory_stats(self):
        """测试 get_memory_stats 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'get_memory_stats')
        assert callable(mem_core.get_memory_stats)


class TestMemCoreExperienceRecall:
    """MemCore 经验回忆测试"""

    def test_unified_experience_recall(self):
        """测试 unified_experience_recall 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'unified_experience_recall')
        assert callable(mem_core.unified_experience_recall)


class TestMemCoreConversationBuffer:
    """MemCore 对话缓冲区测试"""

    def test_update_history(self):
        """测试 update_history 方法"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert hasattr(mem_core, 'update_history')
        assert callable(mem_core.update_history)


class TestMemCoreIntegration:
    """MemCore 集成测试"""

    def test_mem_core_can_be_used_by_agent(self):
        """测试 MemCore 可以被 Agent 使用"""
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.memory_manager = Mock()
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证
        assert mem_core.memory_manager == mock_agent.memory_manager

    def test_mem_core_replaces_direct_imports(self):
        """测试 MemCore 替代直接导入"""
        # 这个测试验证 MemCore 封装了所有认知层模块
        # 准备
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        
        # 执行
        mem_core = MemCore(mock_agent)
        
        # 验证 - MemCore 应该有所有必要的属性
        required_attrs = [
            'memory_manager', 'storage', 'temperature_engine',
            'recall_engine', 'working_memory', 'conversation_buffer',
            'buffer_module', 'growth_log_manager', 'question_queue_manager',
            'tool_memory', 'muscle_memory', 'attachment_manager'
        ]
        
        for attr in required_attrs:
            assert hasattr(mem_core, attr), f"MemCore 缺少属性: {attr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])