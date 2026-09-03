"""
Tier 3B RED+GREEN — OnnxBackend 测试（skipif 保护）

若 ONNX 模型或 numpy 未安装，测试自动 skip，不阻塞 CI。
"""
from __future__ import annotations

import pytest


def _onnx_available() -> bool:
    """检测 ONNX embedding 引擎是否可用"""
    try:
        from neurova.embedding import ONNXEmbeddingEngine
        return ONNXEmbeddingEngine is not None
    except Exception:
        return False


@pytest.mark.skipif(
    not _onnx_available(),
    reason="ONNX 模型或 numpy 未安装，跳过 backend 测试",
)
class TestOnnxBackend:
    """ONNX embedding 引擎真实推理测试（仅当模型可用时运行）"""

    def test_embed_returns_vector(self):
        """embed() 应返回 512 维向量（bge-small-zh-v1.5）"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        engine = get_embedding_engine()
        if engine is None:
            pytest.skip("模型未安装")
        vec = engine.embed("hello world")
        assert len(vec) == 512

    def test_embed_batch(self):
        """embed_batch() 应返回与输入等长的向量列表"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        engine = get_embedding_engine()
        if engine is None:
            pytest.skip("模型未安装")
        vecs = engine.embed_batch(["hello", "world"])
        assert len(vecs) == 2
        assert all(len(v) == 512 for v in vecs)
