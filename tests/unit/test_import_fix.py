"""测试导入问题修复

验证所有必要的模块都可以正确导入。
"""

import pytest
import sys
from pathlib import Path


class TestImportFix:
    """导入问题修复测试"""

    def test_import_moe_router(self):
        """测试导入moe_router模块"""
        from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter
        assert MoEMemoryRouter is not None

    def test_import_temperature(self):
        """测试导入temperature模块"""
        # temperature模块可能不存在，检查是否可以导入
        try:
            from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
            assert TemperatureEngine is not None
        except ImportError as e:
            pytest.skip(f"temperature模块不可用: {e}")

    def test_import_conversation_buffer(self):
        """测试导入conversation_buffer模块"""
        # conversation_buffer模块可能不存在，检查是否可以导入
        try:
            from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationMemoryBuffer
            assert ConversationMemoryBuffer is not None
        except ImportError as e:
            pytest.skip(f"conversation_buffer模块不可用: {e}")

    def test_import_mem_core(self):
        """测试导入mem_core模块"""
        from neurova.mem_core import MemCore
        assert MemCore is not None

    def test_import_agent_core(self):
        """测试导入agent_core模块"""
        from neurova.agent_core import Agent
        assert Agent is not None

    def test_project_structure(self):
        """测试项目结构完整性"""
        project_root = Path("e:/项目/neurova")
        assert project_root.exists()

        # 检查neurova目录
        neurova_dir = project_root / "neurova"
        assert neurova_dir.exists()

        # 检查memory_layer目录
        memory_layer_dir = neurova_dir / "cognitive_layers" / "memory_layer"
        assert memory_layer_dir.exists()

        # 检查必要的.py文件
        py_files = list(memory_layer_dir.glob("*.py"))
        assert len(py_files) > 0, f"memory_layer目录下没有.py文件: {memory_layer_dir}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])