"""
记忆系统安全网测试

验证 memory_layer/ 去重前后的关键行为不变：
1. channels 子系统的冲突检测器可导入、可初始化
2. 向量搜索系统正常工作
3. 兼容层导出正常
"""

import pytest


class TestMemorySystemSafetyNet:
    """记忆系统安全网测试"""

    # ═══ channels 子系统 conflict ═══

    def test_conflict_channels_importable(self):
        """测试 channels 子系统的 conflict 模块可导入"""
        from neurova.cognitive_layers.memory_layer.channels.conflict import (
            ConflictDetector as ChannelsConflictDetector,
            ConflictPair,
        )
        assert ChannelsConflictDetector is not None
        assert ConflictPair is not None

    def test_channels_conflict_detector_init(self):
        """测试 channels 子系统的 ConflictDetector 初始化"""
        from neurova.cognitive_layers.memory_layer.channels.conflict import (
            ConflictDetector,
        )
        detector = ConflictDetector()
        assert detector is not None

    # ═══ 向量搜索系统 ═══

    def test_unified_vector_store_importable(self):
        """测试 unified_vector_store 可导入（核心向量存储）"""
        # 向量原语的公共出口在 §6-181 批 34 搬进 core/vector_math —— 这张安全网钉的是
        # "这些名字可从其单源导入且可调用"，落点随搬家如实改；留在旧落点上再导一份就是第二份出口。
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        from neurova.core import vector_math

        assert UnifiedVectorStore is not None
        assert callable(vector_math.vectorNorm)
        assert callable(vector_math.vectorDot)
        assert callable(vector_math.vectorNormalize)

    def test_unified_vector_store_in_init(self):
        """测试 UnifiedVectorStore 在 memory_layer/__init__.py 中导出"""
        from neurova.cognitive_layers.memory_layer import UnifiedVectorStore
        assert UnifiedVectorStore is not None

    def test_vector_search_importable(self):
        """测试 vector_search 可导入（兼容层使用）"""
        from neurova.cognitive_layers.memory_layer.vector_search import VectorSearch
        assert VectorSearch is not None

    # ═══ 兼容层导出 ═══

    def test_memory_compat_layer_exports(self):
        """测试 neurova.memory 兼容层导出正常"""
        from neurova.memory import (
            UnifiedVectorStore,
            VectorSearch,
        )
        assert UnifiedVectorStore is not None
        assert VectorSearch is not None

    def test_memory_compat_layer_exportsAreBound(self):
        """测试兼容层导出的名字确实绑在模块上"""
        import neurova.memory as memory_mod
        for attr_name in ["UnifiedVectorStore", "VectorSearch"]:
            attr = getattr(memory_mod, attr_name, "MISSING")
            assert attr != "MISSING", f"{attr_name} 应该存在"

    # ═══ 向量工具函数行为 ═══

    def test_vector_norm_behavior(self):
        """测试 vectorNorm 行为不变（§6-181 批 34 搬家前后逐值同）"""
        from neurova.core import vector_math

        assert vector_math.vectorNorm([3, 4]) == 5.0
        assert vector_math.vectorNorm([0, 0]) == 0.0
        assert vector_math.vectorNorm([1]) == 1.0

    def test_vector_dot_behavior(self):
        """测试 vectorDot 行为不变"""
        from neurova.core import vector_math

        assert vector_math.vectorDot([1, 2, 3], [4, 5, 6]) == 32  # 1*4 + 2*5 + 3*6
        assert vector_math.vectorDot([0, 0], [1, 1]) == 0.0

    def test_vector_normalize_behavior(self):
        """测试 vectorNormalize 行为不变（零范数那支返回传入对象本身，不是副本）"""
        from neurova.core import vector_math

        result = vector_math.vectorNormalize([3, 4])
        assert abs(result[0] - 0.6) < 1e-6
        assert abs(result[1] - 0.8) < 1e-6
        zero = [0.0, 0.0]
        assert vector_math.vectorNormalize(zero) is zero


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
