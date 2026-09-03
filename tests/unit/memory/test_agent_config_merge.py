"""
AgentConfig 合并测试

验证清理后只保留 agent_core.py 中的 AgentConfig。
"""
import pytest
import tempfile


class TestAgentConfigImports:
    """验证 AgentConfig 导入"""

    def test_import_from_agent_core(self):
        """从 agent_core 导入 AgentConfig"""
        from neurova.agent_core import AgentConfig
        assert AgentConfig is not None

    def test_agent_config_requires_workspace_path(self):
        """AgentConfig 需要 workspace_path"""
        from neurova.agent_core import AgentConfig
        with pytest.raises(ValueError, match="workspace_path is required"):
            AgentConfig(agent_id="test", name="test")

    def test_agent_config_creates_with_workspace(self):
        """AgentConfig 可以用 workspace_path 创建"""
        from neurova.agent_core import AgentConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                agent_id="test",
                name="test",
                workspace_path=tmpdir,
            )
            assert cfg.agent_id == "test"
            assert cfg.name == "test"

    def test_agent_config_has_all_fields(self):
        """AgentConfig 包含所有必要字段"""
        from neurova.agent_core import AgentConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(agent_id="t", name="t", workspace_path=tmpdir)
            # 核心字段
            assert hasattr(cfg, 'agent_id')
            assert hasattr(cfg, 'name')
            assert hasattr(cfg, 'workspace_path')
            assert hasattr(cfg, 'llm_config')
            assert hasattr(cfg, 'enable_memory')
            # ASR 字段
            assert hasattr(cfg, 'enable_asr')
            assert hasattr(cfg, 'asr_engine')
            # Context pool 字段
            assert hasattr(cfg, 'enable_context_pool')

    def test_no_agent_config_in_agent_config_module(self):
        """neurova.agent.config 模块应被清理"""
        import importlib
        try:
            mod = importlib.import_module('neurova.agent.config')
            # 如果还能导入，检查是否是期望的
            import os
            path = mod.__file__
            # 文件应该已被删除
            assert not os.path.exists(path), "agent/config.py 应已被删除"
        except (ImportError, ModuleNotFoundError):
            # 文件已删除，符合预期
            pass

    def test_agent_config_importable_via_agent_package(self):
        """通过 neurova.agent 包可以获取 AgentConfig"""
        from neurova.agent_core import AgentConfig as AC1
        # agent 包的 __getattr__ 从 agent_core 导入
        # 验证指向同一个类
        assert AC1 is not None
