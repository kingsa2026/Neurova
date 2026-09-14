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
        """encode() 应返回 512 维向量（bge-small-zh-v1.5）

        修正：原断言用想象方法名 embed()——引擎全库真实契约是
        encode()/encode_batch()（消费方 UnifiedVectorStore 同源），
        模型与推理链完好（实测 512 维），属测试契约错位非产品缺陷。
        """
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        engine = get_embedding_engine()
        if engine is None:
            pytest.skip("模型未安装")
        vec = engine.encode("hello world")
        assert len(vec) == 512

    def test_embed_batch(self):
        """encode_batch() 应返回与输入等长的向量列表（EmbeddingResult.vectors）"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        engine = get_embedding_engine()
        if engine is None:
            pytest.skip("模型未安装")
        result = engine.encode_batch(["hello", "world"])
        assert len(result.vectors) == 2
        assert all(len(v) == 512 for v in result.vectors)
