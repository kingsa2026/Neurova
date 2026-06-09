"""
记忆层模块

提供AI系统的记忆管理功能，包括：
- 记忆存储和检索
- MoE（Mixture of Experts）记忆路由器
- 温度衰减和遗忘机制
- 对话缓冲区
- 图遍历检索
"""

import logging as _mem_layer_log

_mem_layer_logger = _mem_layer_log.getLogger(__name__)

# 尝试导入存在的模块（失败时记录 warning 而非静默忽略）
try:
    from .moe_router import MoEMemoryRouter, VectorGatingNetwork, ExpertDrilldownRetriever
except ImportError as _e:
    _mem_layer_logger.debug(f"moe_router 未可用: {_e}")

try:
    from .unified_vector_store import UnifiedVectorStore
except ImportError as _e:
    _mem_layer_logger.debug(f"unified_vector_store 未可用: {_e}")

try:
    from .schema import MemoryCategory, MemoryType, LifecycleStage
except ImportError as _e:
    _mem_layer_logger.debug(f"schema 未可用: {_e}")

try:
    from .conflict_detector_v2 import ConflictDetector
except ImportError as _e:
    _mem_layer_logger.debug(f"conflict_detector_v2 未可用: {_e}")

try:
    from .temperature import TemperatureEngine
except ImportError as _e:
    _mem_layer_logger.debug(f"temperature 未可用: {_e}")

try:
    from .conversation_buffer import ConversationBuffer, ConversationMemoryBuffer, MemoryWriteQueue
except ImportError as _e:
    _mem_layer_logger.debug(f"conversation_buffer 未可用: {_e}")

try:
    from .sleep import SleepConsolidation, MemoryRecord, MergeResult
except ImportError as _e:
    _mem_layer_logger.debug(f"sleep 未可用: {_e}")

try:
    from .graph_traversal import GraphTraversal, MemoryRelation, TraversalPath, TraversalResult
except ImportError as _e:
    _mem_layer_logger.debug(f"graph_traversal 未可用: {_e}")

# 认知图谱存储架构 — 一步到位替换
try:
    from .cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode, MemoryType as CognitiveMemoryType, StorageLayer
except ImportError as _e:
    _mem_layer_logger.debug(f"cognitive_storage_engine 未可用: {_e}")

try:
    from .unified_retriever import UnifiedRetriever
except ImportError as _e:
    _mem_layer_logger.debug(f"unified_retriever 未可用: {_e}")

try:
    from .pattern_crystallizer import PatternCrystallizer
except ImportError as _e:
    _mem_layer_logger.debug(f"pattern_crystallizer 未可用: {_e}")

try:
    from .reasoning_trace_manager import ReasoningTraceManager, ReasoningStep, ReasoningTrace
except ImportError as _e:
    _mem_layer_logger.debug(f"reasoning_trace_manager 未可用: {_e}")

try:
    from .sleep_adapter import SleepConsolidationAdapter
except ImportError as _e:
    _mem_layer_logger.debug(f"sleep_adapter 未可用: {_e}")

# 版本信息
__version__ = "0.2.0"  # 升级版本号
__all__ = [
    # 原有模块
    "MoEMemoryRouter",
    "VectorGatingNetwork",
    "ExpertDrilldownRetriever",
    "UnifiedVectorStore",
    "MemoryCategory",
    "MemoryType",
    "LifecycleStage",
    "ConflictDetector",
    # 认知图谱模块
    "CognitiveStorageEngine",
    "UnifiedMemoryNode",
    "CognitiveMemoryType",
    "StorageLayer",
    "UnifiedRetriever",
    "PatternCrystallizer",
    "ReasoningTraceManager",
    "ReasoningStep",
    "ReasoningTrace",
]