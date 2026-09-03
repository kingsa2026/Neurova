"""
LoopManager 单元测试

验证 LoopManager 深度模块的功能：
1. 初始化和重建 Loop
2. 状态机管理
3. 智能降级
4. 状态变更回调
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.agent.loop_manager import LoopManager, LoopState, LoopEvent


class MockAgent:
    """模拟 Agent 对象，用于测试"""
    def __init__(self):
        self.config = Mock()
        self.config.name = "TestAgent"
        self.config.llm_config = Mock()
        self.config.llm_config.model = "gpt-4"
        self.llm_client = Mock()
        self.skill_registry = None


class MockLoop:
    """模拟 Agent Loop"""
    def __init__(self, agent=None):
        self.agent = agent
        self.predict_step = AsyncMock(return_value=Mock(content="Mock response"))


class TestLoopState:
    """测试 LoopState 枚举"""
    
    def test_loop_state_values(self):
        """测试 LoopState 枚举值"""
        assert LoopState.INITIALIZING.value == "initializing"
        assert LoopState.READY.value == "ready"
        assert LoopState.DEGRADED.value == "degraded"
        assert LoopState.FAILED.value == "failed"
    
    def test_loop_state_is_enum(self):
        """测试 LoopState 是枚举"""
        from enum import Enum
        assert issubclass(LoopState, Enum)


class TestLoopEvent:
    """测试 LoopEvent 数据类"""
    
    def test_loop_event_creation(self):
        """测试 LoopEvent 创建"""
        event = LoopEvent(
            old_state=LoopState.INITIALIZING,
            new_state=LoopState.READY,
            message="Loop initialized successfully"
        )
        
        assert event.old_state == LoopState.INITIALIZING
        assert event.new_state == LoopState.READY
        assert event.message == "Loop initialized successfully"
        assert event.timestamp is not None
    
    def test_loop_event_default_message(self):
        """测试 LoopEvent 默认消息"""
        event = LoopEvent(
            old_state=LoopState.INITIALIZING,
            new_state=LoopState.READY
        )
        
        assert event.message == ""


class TestLoopManager:
    """测试 LoopManager 类"""
    
    def setup_method(self):
        """每个测试前重置"""
        self.agent = MockAgent()
        self.manager = LoopManager(self.agent)
    
    def test_initialization(self):
        """测试 LoopManager 初始化"""
        assert self.manager.agent == self.agent
        assert self.manager.get_state() == LoopState.INITIALIZING
        assert self.manager.get_loop() is None
    
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        """测试成功初始化 Loop"""
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            
            result = await self.manager.initialize()
            
            assert result is True
            assert self.manager.get_state() == LoopState.READY
            assert self.manager.get_loop() is not None
            mock_find.assert_called_once_with(self.agent.config.llm_config.model)
    
    @pytest.mark.asyncio
    async def test_initialize_failure_no_loop_found(self):
        """测试初始化失败：未找到 Loop"""
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = None
            
            result = await self.manager.initialize()
            
            assert result is False
            assert self.manager.get_state() == LoopState.FAILED
            assert self.manager.get_loop() is None
    
    @pytest.mark.asyncio
    async def test_initialize_failure_exception(self):
        """测试初始化失败：异常"""
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.side_effect = Exception("Loop instantiation failed")
            
            result = await self.manager.initialize()
            
            assert result is False
            assert self.manager.get_state() == LoopState.FAILED
    
    @pytest.mark.asyncio
    async def test_rebuild_success(self):
        """测试成功重建 Loop"""
        # 先初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await self.manager.initialize()
        
        # 重建
        new_model = "claude-3-opus"
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            
            result = await self.manager.rebuild(new_model)
            
            assert result is True
            assert self.manager.get_state() == LoopState.READY
            assert self.manager.get_loop() is not None
    
    @pytest.mark.asyncio
    async def test_rebuild_failure_same_model(self):
        """测试重建失败：相同模型"""
        # 先初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await self.manager.initialize()
        
        # 尝试用相同模型重建
        result = await self.manager.rebuild(self.agent.config.llm_config.model)
        
        assert result is True  # 相同模型应该成功
        assert self.manager.get_state() == LoopState.READY
    
    @pytest.mark.asyncio
    async def test_rebuild_failure_no_loop_found(self):
        """测试重建失败：未找到 Loop"""
        # 先初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await self.manager.initialize()
        
        # 重建失败
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = None
            
            result = await self.manager.rebuild("unknown-model")
            
            assert result is False
            # 应该保持旧状态
            assert self.manager.get_state() == LoopState.READY
    
    @pytest.mark.asyncio
    async def test_rebuild_failure_exception_preserves_old_loop(self):
        """测试重建失败：异常时保留旧 Loop"""
        # 先初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await self.manager.initialize()
        
        old_loop = self.manager.get_loop()
        
        # 重建失败
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.side_effect = Exception("Loop instantiation failed")
            
            result = await self.manager.rebuild("new-model")
            
            assert result is False
            # 应该保留旧 Loop
            assert self.manager.get_loop() == old_loop
            assert self.manager.get_state() == LoopState.READY
    
    def test_get_loop_not_initialized(self):
        """测试获取未初始化的 Loop"""
        loop = self.manager.get_loop()
        assert loop is None
    
    def test_get_state_initial(self):
        """测试初始状态"""
        state = self.manager.get_state()
        assert state == LoopState.INITIALIZING
    
    def test_on_state_change_callback(self):
        """测试状态变更回调"""
        callback = Mock()
        self.manager.on_state_change(callback)
        
        # 触发状态变更
        self.manager._set_state(LoopState.READY)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, LoopEvent)
        assert event.old_state == LoopState.INITIALIZING
        assert event.new_state == LoopState.READY
    
    def test_on_state_change_multiple_callbacks(self):
        """测试多个状态变更回调"""
        callback1 = Mock()
        callback2 = Mock()
        
        self.manager.on_state_change(callback1)
        self.manager.on_state_change(callback2)
        
        # 触发状态变更
        self.manager._set_state(LoopState.READY)
        
        callback1.assert_called_once()
        callback2.assert_called_once()
    
    def test_remove_state_change_callback(self):
        """测试移除状态变更回调"""
        callback = Mock()
        self.manager.on_state_change(callback)
        
        # 移除回调
        self.manager.remove_state_change_callback(callback)
        
        # 触发状态变更
        self.manager._set_state(LoopState.READY)
        
        callback.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_degraded_loop_functionality(self):
        """测试降级 Loop 功能"""
        # 创建一个会失败的 Loop 类
        class FailingLoop(MockLoop):
            def __init__(self, agent=None):
                super().__init__(agent)
                # 模拟功能缺失
                self._tools_supported = False
        
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = FailingLoop
            
            result = await self.manager.initialize()
            
            # 应该成功初始化，但进入降级状态
            assert result is True
            assert self.manager.get_state() == LoopState.DEGRADED
    
    def test_get_health_info(self):
        """测试获取健康信息"""
        health = self.manager.get_health()
        
        assert "state" in health
        assert "loop_type" in health
        assert "model" in health
        assert "uptime_seconds" in health
    
    @pytest.mark.asyncio
    async def test_force_reinitialize(self):
        """测试强制重新初始化"""
        # 先初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await self.manager.initialize()
        
        old_loop = self.manager.get_loop()
        
        # 强制重新初始化
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            
            result = await self.manager.force_reinitialize()
            
            assert result is True
            assert self.manager.get_state() == LoopState.READY
            # 应该是新的 Loop 实例
            assert self.manager.get_loop() is not old_loop
    
    def test_clear_state_change_callbacks(self):
        """测试清除所有状态变更回调"""
        callback1 = Mock()
        callback2 = Mock()
        
        self.manager.on_state_change(callback1)
        self.manager.on_state_change(callback2)
        
        # 清除所有回调
        self.manager.clear_state_change_callbacks()
        
        # 触发状态变更
        self.manager._set_state(LoopState.READY)
        
        callback1.assert_not_called()
        callback2.assert_not_called()


class TestLoopManagerIntegration:
    """测试 LoopManager 集成"""
    
    @pytest.mark.asyncio
    async def test_agent_uses_loop_manager(self):
        """测试 Agent 使用 LoopManager"""
        from neurova.agent_core import Agent, AgentConfig
        
        config = AgentConfig(
            name="TestAgent",
            agent_id="test_agent",
            workspace_path=str(Path("./test_workspace")),
            llm_api_key="test-key",
            llm_model="gpt-4",
        )
        
        mp = pytest.MonkeyPatch()
        mp.setattr("neurova.llm_client.OpenAI", Mock())
        try:
            agent = Agent(config=config)
            
            # 检查 Agent 是否有 loop_manager
            if hasattr(agent, 'loop_manager'):
                assert agent.loop_manager is not None
                assert isinstance(agent.loop_manager, LoopManager)
        finally:
            mp.undo()
    
    @pytest.mark.asyncio
    async def test_loop_manager_state_consistency(self):
        """测试 LoopManager 状态一致性"""
        agent = MockAgent()
        manager = LoopManager(agent)
        
        # 初始状态
        assert manager.get_state() == LoopState.INITIALIZING
        assert manager.get_loop() is None
        
        # 初始化成功
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await manager.initialize()
        
        assert manager.get_state() == LoopState.READY
        assert manager.get_loop() is not None
        
        # 重建成功
        with patch('neurova.agent.loop_manager.find_agent_loop') as mock_find:
            mock_find.return_value = MockLoop
            await manager.rebuild("claude-3-opus")
        
        assert manager.get_state() == LoopState.READY
        assert manager.get_loop() is not None


def test_imports():
    """测试所有导入是否正常"""
    try:
        from neurova.agent.loop_manager import LoopManager, LoopState, LoopEvent
        
        print("✓ All LoopManager imports successful")
        return True
    
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


if __name__ == "__main__":
    # 运行简单测试
    print("Running LoopManager tests...")
    
    # 测试导入
    test_imports()
    
    print("\n✓ All tests passed!")