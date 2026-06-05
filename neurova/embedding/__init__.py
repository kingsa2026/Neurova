"""
Embedding Module - 向量嵌入引擎

支持 ONNX Runtime 本地推理，开箱即用。
"""

from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine, EmbeddingResult

__all__ = ["ONNXEmbeddingEngine", "EmbeddingResult"]
