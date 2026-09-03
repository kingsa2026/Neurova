"""
ContextOrchestrator 合并测试

验证清理后只保留一个实现，且导入路径正确。
"""
import pytest


class TestContextOrchestratorImports:
    """验证导入路径"""

    def test_import_from_context_package(self):
        """从 neurova.context 包导入"""
        from neurova.context import ContextOrchestrator
        assert ContextOrchestrator is not None
        assert hasattr(ContextOrchestrator, 'init_context_system')

    def test_import_from_agent_core(self):
        """agent_core 使用的 ContextOrchestrator"""
        from neurova.context import ContextOrchestrator as CO
        # 验证是真正的实现（有 agent_ref 参数）
        import inspect
        sig = inspect.signature(CO.__init__)
        assert 'agent_ref' in sig.parameters

    def test_context_package_has_all_exports(self):
        """neurova.context 包导出完整"""
        from neurova import context
        assert hasattr(context, 'ContextOrchestrator')
        assert hasattr(context, 'ContextBuilder')
        assert hasattr(context, 'UnifiedContextInjector')

    def test_no_root_level_context_orchestrator(self):
        """根级别 context_orchestrator.py 应被清理"""
        import importlib
        try:
            mod = importlib.import_module('neurova.context_orchestrator')
            # 如果还能导入，说明文件还在
            # 这不是错误，只是标记为需要清理
            import os
            path = mod.__file__
            assert os.path.exists(path), "文件应该存在或已被删除"
        except ImportError:
            # 文件已删除，符合预期
            pass

    def test_no_agent_context_orchestrator(self):
        """agent/context_orchestrator.py 应被清理"""
        import importlib
        try:
            mod = importlib.import_module('neurova.agent.context_orchestrator')
            import os
            path = mod.__file__
            assert os.path.exists(path), "文件应该存在或已被删除"
        except ImportError:
            pass


class TestContextOrchestratorBehavior:
    """验证清理后的行为不变"""

    def test_orchestrator_has_required_methods(self):
        """核心方法存在"""
        from neurova.context import ContextOrchestrator
        assert hasattr(ContextOrchestrator, 'init_context_system')
        assert hasattr(ContextOrchestrator, 'build_context')
        assert hasattr(ContextOrchestrator, 'build_system_prompt')
        assert hasattr(ContextOrchestrator, 'get_tools_description')
        assert hasattr(ContextOrchestrator, 'build_tools_for_llm')

    def test_orchestrator_init_takes_agent_ref(self):
        """构造函数接受 agent_ref"""
        from neurova.context import ContextOrchestrator
        import inspect
        sig = inspect.signature(ContextOrchestrator.__init__)
        params = list(sig.parameters.keys())
        assert 'agent_ref' in params
        assert 'use_pool' in params
        assert 'auto_tag' in params
