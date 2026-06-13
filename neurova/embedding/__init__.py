"""
Embedding Module - 向量嵌入引擎

支持 ONNX Runtime 本地推理，开箱即用。
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.embedding.onnx_embedding import EmbeddingResult, ONNXEmbeddingEngine
except ImportError as _e:
    _logger.debug("ONNXEmbeddingEngine/EmbeddingResult 未可用: %s", _e)
    ONNXEmbeddingEngine = None
    EmbeddingResult = None

__all__ = ["ONNXEmbeddingEngine", "EmbeddingResult"]
