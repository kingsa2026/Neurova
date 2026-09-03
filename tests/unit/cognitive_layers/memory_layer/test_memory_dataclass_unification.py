"""
Tier 4A.1 RED 测试 — Memory dataclass 统一

验证：
1. mem_core.Memory 已删除（应抛 ImportError）
2. memory_rw_manager / cognitive / neurova.memory 三处 Memory 全部指向 models.Memory
3. MemoryRecord.to_memory() / from_memory() 双向转换
4. UnifiedMemoryNode.to_memory() / from_memory() 双向转换
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

import pytest


class TestDataclassUnificationImports:
    """验证 mem_core.Memory 已删除 + 3 处使用方指向 models.Memory"""

    def test_mem_core_no_Memory_class(self):
        """RED: from neurova.mem_core import Memory 应抛 ImportError"""
        # 清除缓存以避免之前导入的 Memory 仍可见
        for mod_name in list(sys.modules.keys()):
            if mod_name == "neurova.mem_core" or mod_name.startswith("neurova.mem_core."):
                # 重新加载以反映最新源码
                mod = sys.modules.get(mod_name)
                if mod is not None and hasattr(mod, "Memory"):
                    # 若模块仍含 Memory 属性，说明尚未删除
                    with pytest.raises((ImportError, AttributeError)):
                        # 检查 mem_core 模块级 Memory 已不存在
                        import neurova.mem_core as mc

                        # 重新加载以反映最新源码
                        importlib.reload(mc)
                        _ = mc.Memory  # 应抛 AttributeError
                    return
        # 若模块未加载或无 Memory 属性，验证导入失败
        if "neurova.mem_core" in sys.modules:
            mod = sys.modules["neurova.mem_core"]
            assert not hasattr(mod, "Memory"), (
                "RED: mem_core.Memory 仍存在，应已删除（Tier 4A.2）"
            )
        else:
            # 直接尝试导入，应失败
            try:
                from neurova.mem_core import Memory  # noqa: F401

                pytest.fail("RED: from neurova.mem_core import Memory 仍可导入，应已删除")
            except (ImportError, AttributeError):
                pass  # 预期

    def test_memory_rw_manager_uses_models_Memory(self):
        """RED: memory_rw_manager.Memory 应 is models.Memory"""
        from neurova.cognitive_layers.memory_layer.models import Memory as ModelsMemory

        # 重新加载以反映最新源码
        import neurova.memory_rw_manager as mrw

        importlib.reload(mrw)
        assert mrw.Memory is ModelsMemory, (
            f"RED: memory_rw_manager.Memory 应 is models.Memory, 实际: {mrw.Memory}"
        )

    def test_cognitive_init_uses_models_Memory(self):
        """RED: neurova.cognitive.Memory 应 is models.Memory"""
        from neurova.cognitive_layers.memory_layer.models import Memory as ModelsMemory

        import neurova.cognitive as cog

        importlib.reload(cog)
        # cognitive.Memory 可能为 None（ImportError 降级），统一后应非 None 且 is ModelsMemory
        assert cog.Memory is not None, "RED: cognitive.Memory 不应为 None"
        assert cog.Memory is ModelsMemory, (
            f"RED: cognitive.Memory 应 is models.Memory, 实际: {cog.Memory}"
        )

    def test_memory_init_uses_models_Memory(self):
        """RED: neurova.memory.Memory 应 is models.Memory"""
        from neurova.cognitive_layers.memory_layer.models import Memory as ModelsMemory

        import neurova.memory as mem

        importlib.reload(mem)
        assert mem.Memory is not None, "RED: neurova.memory.Memory 不应为 None"
        assert mem.Memory is ModelsMemory, (
            f"RED: neurova.memory.Memory 应 is models.Memory, 实际: {mem.Memory}"
        )


class TestMemoryRecordConversion:
    """验证 MemoryRecord.to_memory / from_memory 双向转换"""

    def test_MemoryRecord_to_memory(self):
        """RED: MemoryRecord(...).to_memory() 返回 models.Memory 实例"""
        from neurova.cognitive_layers.memory_layer.models import Memory
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord

        record = MemoryRecord(
            id="rec_001",
            content="测试内容",
            memory_type="semantic",
            owner="default",
            importance=0.8,  # 0+ 量纲
            access_count=3,
            agent_id="agent_x",
            neuser_id="neu_y",
            user_id="u_z",
        )
        mem = record.to_memory()
        assert isinstance(mem, Memory), f"to_memory 应返回 Memory, 实际: {type(mem)}"
        assert mem.id == "rec_001"
        assert mem.content == "测试内容"
        # importance 量纲转换：0.8 (0+) → 80.0 (0-100)
        assert mem.importance == 80.0, f"importance 应为 80.0, 实际: {mem.importance}"
        assert mem.agent_id == "agent_x"
        assert mem.access_count == 3

    def test_MemoryRecord_from_memory(self):
        """RED: MemoryRecord.from_memory(Memory(...)) 返回 MemoryRecord"""
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord

        mem = Memory(
            id="mem_002",
            content="反向转换",
            memory_type=MemoryType.SEMANTIC,
            importance=50.0,  # 0-100 量纲
            agent_id="a1",
            neuser_id="n1",
            user_id="u1",
            access_count=5,
        )
        record = MemoryRecord.from_memory(mem)
        assert isinstance(record, MemoryRecord), (
            f"from_memory 应返回 MemoryRecord, 实际: {type(record)}"
        )
        assert record.id == "mem_002"
        # importance 反向转换：50.0 (0-100) → 0.5 (0+)
        assert record.importance == 0.5, f"importance 应为 0.5, 实际: {record.importance}"
        assert record.agent_id == "a1"
        assert record.access_count == 5


class TestUnifiedMemoryNodeConversion:
    """验证 UnifiedMemoryNode.to_memory / from_memory 双向转换"""

    def test_UnifiedMemoryNode_to_memory(self):
        """RED: UnifiedMemoryNode(...).to_memory() 返回 models.Memory"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode,
            MemoryType as CSEMemoryType,
            StorageLayer,
        )
        from neurova.cognitive_layers.memory_layer.models import Memory

        node = UnifiedMemoryNode(
            id="node_001",
            content="节点内容",
            memory_type=CSEMemoryType.SEMANTIC,
            temperature=75.0,  # 0-100 量纲
            layer=StorageLayer.L1_HOT,
            access_count=2,
        )
        mem = node.to_memory()
        assert isinstance(mem, Memory), f"to_memory 应返回 Memory, 实际: {type(mem)}"
        assert mem.id == "node_001"
        assert mem.content == "节点内容"
        # temperature 量纲一致：0-100
        assert mem.temperature == 75.0, f"temperature 应为 75.0, 实际: {mem.temperature}"
        assert mem.access_count == 2

    def test_UnifiedMemoryNode_from_memory(self):
        """RED: UnifiedMemoryNode.from_memory(Memory(...)) 返回 UnifiedMemoryNode"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode,
        )
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType

        mem = Memory(
            id="mem_003",
            content="节点反向",
            memory_type=MemoryType.SEMANTIC,
            temperature=60.0,  # 0-100 量纲
            access_count=7,
        )
        node = UnifiedMemoryNode.from_memory(mem)
        assert isinstance(node, UnifiedMemoryNode), (
            f"from_memory 应返回 UnifiedMemoryNode, 实际: {type(node)}"
        )
        assert node.id == "mem_003"
        assert node.content == "节点反向"
        # temperature 量纲一致：0-100
        assert node.temperature == 60.0, f"temperature 应为 60.0, 实际: {node.temperature}"
        assert node.access_count == 7
