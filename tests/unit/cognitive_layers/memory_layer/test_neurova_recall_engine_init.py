"""
Tier 4B.1 RED 测试 — NeurovaRecallEngine 构造签名验证

验证 Bug 9：mem_core.py:376-393 使用错误构造签名
   错误签名: (storage=, temperature_engine=, emotion_analyzer=, tkg=, vector_search=, config=)
   真实签名: (memory_manager=, max_workers=, timeout_seconds=, intent_detector=,
             intent_strategy=, use_plugins=, registry=, fusion_mode=, density_scale=)

注：这两个测试 PASS（直接构造，绕过 mem_core.py），用于验证真实签名稳定。
   Bug 9 的 RED 验证由集成测试 test_agent_recall_engine_init.py 完成（在 4B.3 GREEN 后）。
"""
from __future__ import annotations

import pytest


class TestRecallEngineInit:
    """NeurovaRecallEngine 用真实签名构造不应抛 TypeError"""

    def test_recall_engine_init_no_type_error(self, tmp_path):
        """NeurovaRecallEngine(memory_manager=mgr) 应成功构造"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mgr = MemoryManager(db_path=str(tmp_path / "test_recall.db"))
        try:
            # 真实签名：memory_manager 是唯一注入点
            engine = NeurovaRecallEngine(memory_manager=mgr)
            assert engine is not None
            assert engine.memory_manager is mgr
        finally:
            if hasattr(mgr, "close"):
                mgr.close()

    def test_recall_engine_init_accepts_optional_params(self):
        """NeurovaRecallEngine 接受 max_workers / timeout_seconds / fusion_mode"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine(
            memory_manager=None,
            max_workers=2,
            timeout_seconds=5.0,
            fusion_mode="legacy",
        )
        assert engine.max_workers == 2
        assert engine.timeout_seconds == 5.0
        assert engine.fusion_mode == "legacy"

    def test_recall_engine_init_rejects_wrong_kwargs(self):
        """RED 验证：错误签名 storage=/temperature_engine= 应抛 TypeError

        这是 Bug 9 的核心：mem_core.py 用了错误参数名。
        """
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        with pytest.raises(TypeError) as exc_info:
            NeurovaRecallEngine(
                storage=None,
                temperature_engine=None,
                config={},
            )
        # 错误信息应提示不接受这些参数
        assert "storage" in str(exc_info.value) or "unexpected keyword" in str(exc_info.value)
