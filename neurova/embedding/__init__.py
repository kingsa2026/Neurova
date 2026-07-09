"""
Embedding Module - 向量嵌入引擎

支持 ONNX Runtime 本地推理，开箱即用。
"""

import threading
from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from neurova.embedding.onnx_embedding import EmbeddingResult, ONNXEmbeddingEngine
except ImportError as _e:
    _logger.debug("ONNXEmbeddingEngine/EmbeddingResult 未可用: %s", _e)
    ONNXEmbeddingEngine = None
    EmbeddingResult = None

__all__ = ["ONNXEmbeddingEngine", "EmbeddingResult", "get_embedding_engine", "_reset_embedding_engine"]

# 全局单例（懒加载）
_embedding_engine = None
_embedding_lock = threading.Lock()


def get_embedding_engine():
    """获取全局 embedding 引擎单例（懒加载）

    Bug 12 修复前置：提供统一工厂入口，供 SemanticSearch 等模块懒加载。

    Returns:
        ONNXEmbeddingEngine 实例，若模型未安装或初始化失败返回 None
    """
    global _embedding_engine
    if _embedding_engine is not None:
        return _embedding_engine
    with _embedding_lock:
        if _embedding_engine is not None:
            return _embedding_engine
        if ONNXEmbeddingEngine is None:
            _logger.warning("ONNXEmbeddingEngine 不可用，embedding 工厂返回 None")
            return None
        try:
            _embedding_engine = ONNXEmbeddingEngine()
            _logger.info("全局 ONNXEmbeddingEngine 已初始化")
        except Exception as e:
            _logger.warning("ONNXEmbeddingEngine 初始化失败: %s", e)
            _embedding_engine = None
    return _embedding_engine


def _reset_embedding_engine():
    """测试用：重置单例

    生产代码不应调用此函数。
    """
    global _embedding_engine
    _embedding_engine = None
