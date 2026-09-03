"""
Tier 1.1 导入冒烟测试 — 死代码清理前的基线

目的：建立删除前的基线，确保后续删除 schema.py / search_mixin.py / bm25.py /
proactive_recall.py / neurova/memory/ 整个包后，下列关键导入仍可用。

注意：
- MemoryManager 不在 __init__.py 包级别导出，需从 .manager 子模块导入
- CognitiveStorageEngine / UnifiedMemoryNode 在 __init__.py 已导出
- Memory / MemoryCategory / LifecycleStage 在 .models 子模块
"""

import pytest


class TestImportSafety:
    """关键模块导入安全性测试"""

    def test_import_memory_layer_package(self):
        """import memory_layer 包不报错"""
        import neurova.cognitive_layers.memory_layer as pkg
        assert pkg is not None

    def test_import_memory_manager(self):
        """从 .manager 子模块导入 MemoryManager"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        assert MemoryManager is not None
        assert hasattr(MemoryManager, "__init__")

    def test_import_get_memory_manager_factory(self):
        """工厂函数 get_memory_manager 可用"""
        from neurova.cognitive_layers.memory_layer.manager import get_memory_manager
        assert callable(get_memory_manager)

    def test_import_models_memory(self):
        """从 .models 导入 Memory dataclass"""
        from neurova.cognitive_layers.memory_layer.models import Memory
        assert Memory is not None
        # 验证关键字段存在（22 字段）
        fields = {"id", "content", "memory_type", "category", "lifecycle_stage",
                  "perspective", "emotion", "temperature", "importance", "access_count",
                  "embedding", "metadata", "agent_id", "neuser_id", "user_id",
                  "shared", "share_group_ids", "created_at", "updated_at",
                  "last_accessed_at", "isolation_context"}
        actual_fields = set(Memory.__dataclass_fields__.keys())
        missing = fields - actual_fields
        assert not missing, f"Memory dataclass 缺失字段: {missing}"

    def test_import_models_enums(self):
        """从 .models 导入枚举类（LifecycleStage / MemoryCategory / MemoryType）"""
        from neurova.cognitive_layers.memory_layer.models import (
            LifecycleStage, MemoryCategory, MemoryType,
        )
        assert LifecycleStage is not None
        assert MemoryCategory is not None
        assert MemoryType is not None

    def test_import_cognitive_storage_engine(self):
        """从包级别导入 CognitiveStorageEngine"""
        from neurova.cognitive_layers.memory_layer import CognitiveStorageEngine
        assert CognitiveStorageEngine is not None

    def test_import_unified_memory_node(self):
        """从包级别导入 UnifiedMemoryNode"""
        from neurova.cognitive_layers.memory_layer import UnifiedMemoryNode
        assert UnifiedMemoryNode is not None

    def test_import_cognitive_storage_engine_module(self):
        """从子模块导入 UnifiedMemoryNode（直接路径）"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode, MemoryType as CognitiveMemoryType, StorageLayer,
        )
        assert UnifiedMemoryNode is not None
        assert CognitiveMemoryType is not None
        assert StorageLayer is not None

    def test_import_api_app(self):
        """API 层 app 模块可导入（验证后端入口完整性）"""
        import neurova.api.app as api_app
        assert api_app is not None

    def test_import_temperature_engine(self):
        """TemperatureEngine 可导入（前次会话修复的核心模块）"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        assert TemperatureEngine is not None

    def test_import_event_bus(self):
        """EventBus 可导入（前次会话修复的线程安全模块）"""
        from neurova.cognitive_layers.memory_layer.bus_event import EventBus
        assert EventBus is not None
