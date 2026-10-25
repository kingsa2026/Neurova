"""
Embedding Module - 向量嵌入引擎

支持 ONNX Runtime 本地推理，开箱即用。
"""

import threading
from neurova.core.logger import get_logger
_logger = get_logger(__name__)

from neurova.embedding.onnx_embedding import EmbeddingResult, ONNXEmbeddingEngine

__all__ = ["ONNXEmbeddingEngine", "EmbeddingResult", "get_embedding_engine", "_reset_embedding_engine", "reset_embedding_engine"]

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

    丢弃引用**之前**先把旧引擎关掉：`InferenceSession` 持有原生内存，
    直接置 None 只是把它交给 GC，而 GC 回收时机不可控。单进程跑近八千档时
    逐档 reset 会各留一个 session，累积顶到 runner 内存上限被 SIGKILL
    （pipeline-3 的 137）。故这里主动释放，而不是指望 GC。
    """
    global _embedding_engine
    previous = _embedding_engine
    _embedding_engine = None
    if previous is None:
        return
    # 走同步的释放入口：本函数可能在**已有事件循环**里被调用（异步用例、异步服务
    # 的测试隔离），那里 asyncio.run() 会抛 RuntimeError，协程从不执行、
    # session 也就不释放——泄漏会在异步上下文里原样复发。
    release = getattr(previous, "releaseBackend", None)
    if not callable(release):
        return
    try:
        release()
    except Exception as e:
        # 释放动作不得把重置流程变成崩溃（缺 close() 的后端已在引擎侧 fail-soft）。
        _logger.warning("重置 embedding 引擎时释放失败: %s", e)


def reset_embedding_engine():
    """公有重置入口（P3-e）：与 _reset_embedding_engine 等价，供测试隔离与运维重建。"""
    _reset_embedding_engine()
