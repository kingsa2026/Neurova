"""
P0 清理安全网测试

验证清理前后的关键行为不变：
1. ToolExecutor 从 neurova.tool_executor 正确导入
2. ToolExecutor 核心方法可用
3. Agent 初始化不依赖 sys.path hack
4. 删除的死文件确实无导入
"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path


class TestP0SafetyNet:
    """P0 清理安全网"""

    def test_tool_executor_import_path(self):
        """测试 ToolExecutor 活跃版本的导入路径"""
        # RED: 验证活跃版本从 neurova.tool_executor 导入
        from neurova.tool_executor import ToolExecutor
        assert ToolExecutor is not None
        
        # 验证类名
        assert ToolExecutor.__name__ == "ToolExecutor"

    def test_tool_executor_init(self):
        """测试 ToolExecutor 初始化"""
        from neurova.tool_executor import ToolExecutor
        
        # 创建 mock agent
        mock_agent = Mock()
        mock_agent._skill_registry = None
        mock_agent.tool_router = None
        mock_agent.tool_memory = None
        mock_agent.tool_lifecycle = None
        mock_agent.skill_packer = None
        mock_agent.config = Mock()
        mock_agent.config.user_id = "test_user"
        mock_agent.config.agent_id = "test_agent"
        
        # 初始化
        executor = ToolExecutor(agent_ref=mock_agent)
        assert executor is not None
        assert executor._agent is mock_agent

    def test_tool_executor_has_core_methods(self):
        """测试 ToolExecutor 有核心方法"""
        from neurova.tool_executor import ToolExecutor
        
        mock_agent = Mock()
        executor = ToolExecutor(agent_ref=mock_agent)
        
        # 验证核心方法存在
        assert hasattr(executor, "execute_text_tool_calls")
        assert hasattr(executor, "execute_from_memory")
        assert hasattr(executor, "execute_from_memory_async")
        assert hasattr(executor, "execute_skill_tool")
        assert hasattr(executor, "execute_cli_tool")
        # 注意：活跃版本的方法名是 on_tool_executed（无下划线前缀）
        # 但实际代码中是 on_tool_executed（无下划线），不是 _on_tool_executed
        assert hasattr(executor, "on_tool_executed") or hasattr(executor, "_on_tool_executed")

    def test_tool_executor_property_proxies(self):
        """测试 ToolExecutor 属性代理"""
        from neurova.tool_executor import ToolExecutor
        
        # 创建带属性的 mock agent
        mock_agent = Mock()
        mock_agent._skill_registry = "skill_registry_value"
        mock_agent.tool_router = "tool_router_value"
        mock_agent.tool_memory = "tool_memory_value"
        mock_agent.tool_lifecycle = "tool_lifecycle_value"
        mock_agent.skill_packer = "skill_packer_value"
        mock_agent.config = "config_value"
        
        executor = ToolExecutor(agent_ref=mock_agent)
        
        # 验证属性代理
        assert executor._skill_registry == "skill_registry_value"
        assert executor.tool_router == "tool_router_value"
        assert executor.tool_memory == "tool_memory_value"
        assert executor.tool_lifecycle == "tool_lifecycle_value"
        assert executor.skill_packer == "skill_packer_value"
        assert executor.config == "config_value"

    def test_tool_executor_property_proxies_missing_attrs(self):
        """测试 ToolExecutor 属性代理缺失属性时返回 None"""
        from neurova.tool_executor import ToolExecutor
        
        # 创建空 mock agent
        mock_agent = Mock(spec=[])  # 无任何属性
        executor = ToolExecutor(agent_ref=mock_agent)
        
        # 验证缺失属性返回 None
        assert executor._skill_registry is None
        assert executor.tool_router is None
        assert executor.tool_memory is None
        assert executor.tool_lifecycle is None
        assert executor.skill_packer is None
        assert executor.config is None

    def test_agent_core_no_sys_path_dependency(self):
        """测试 Agent 初始化不依赖 sys.path hack"""
        import sys
        original_path = sys.path.copy()
        
        try:
            # 移除可能由 agent_core.py 添加的路径
            project_root = str(Path(__file__).parent.parent.parent)
            if project_root in sys.path:
                sys.path.remove(project_root)
            
            # 重新导入 agent_core，应该成功
            import importlib
            import neurova.agent_core
            importlib.reload(neurova.agent_core)
            
            from neurova.agent_core import Agent, AgentConfig
            
            # 验证可以创建配置
            config = AgentConfig(
                name="test",
                agent_id="test_001",
                workspace_path="/tmp/test"
            )
            assert config.name == "test"
            
        finally:
            # 恢复 sys.path
            sys.path = original_path

    def test_dead_files_not_imported(self):
        """测试死文件确实无导入"""
        import sys
        
        # 验证这些模块不在 sys.modules 中（未被导入）
        dead_modules = [
            "neurova.context_legacy",
            "neurova.cognitive_layers.memory_layer.retrieval_facade",
            "neurova.cognitive_layers.memory_layer.memory_retrieval_facade",
        ]
        
        for module_name in dead_modules:
            assert module_name not in sys.modules, f"{module_name} 不应被导入"

    def test_agent_tool_executor_not_used(self):
        """测试 neurova.agent.tool_executor 不被使用
        
        清理后验证：
        - neurova.tool_executor 是活跃版本
        - neurova.agent.tool_executor 已删除
        """
        import sys
        
        # 验证活跃版本已导入
        assert "neurova.tool_executor" in sys.modules, \
            "neurova.tool_executor 应该被导入"
        
        # 验证旧版本不在 sys.modules 中
        assert "neurova.agent.tool_executor" not in sys.modules, \
            "neurova.agent.tool_executor 不应被导入（已删除）"
        
        # 验证从 neurova.agent 导入 ToolExecutor 仍然可用
        from neurova.agent import ToolExecutor
        assert ToolExecutor is not None
        
        # 验证导入的是活跃版本
        from neurova.tool_executor import ToolExecutor as ActiveToolExecutor
        assert ToolExecutor is ActiveToolExecutor, \
            "neurova.agent.ToolExecutor 应该是 neurova.tool_executor.ToolExecutor 的别名"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
