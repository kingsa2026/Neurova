"""
记忆层模块

提供AI系统的记忆管理功能，包括：
- 记忆存储和检索
- MoE（Mixture of Experts）记忆路由器
- 温度衰减和遗忘机制
- 对话缓冲区
- 图遍历检索
"""

# 尝试导入存在的模块
try:
    from .moe_router import MoEMemoryRouter, VectorGatingNetwork, ExpertDrilldownRetriever
except ImportError:
    pass

try:
    from .unified_vector_store import UnifiedVectorStore
except ImportError:
    pass

try:
    from .schema import MemoryCategory, MemoryType, LifecycleStage
except ImportError:
    pass

try:
    from .conflict_detector_v2 import ConflictDetector
except ImportError:
    pass

try:
    from .temperature import TemperatureEngine
except ImportError:
    pass

try:
    from .conversation_buffer import ConversationBuffer, ConversationMemoryBuffer, MemoryWriteQueue
except ImportError:
    pass

try:
    from .sleep import SleepConsolidation, MemoryRecord, MergeResult
except ImportError:
    pass

try:
    from .graph_traversal import GraphTraversal, MemoryRelation, TraversalPath, TraversalResult
except ImportError:
    pass

# 认知图谱存储架构 — 一步到位替换
try:
    from .cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode, MemoryType as CognitiveMemoryType, StorageLayer
except ImportError:
    pass

try:
    from .unified_retriever import UnifiedRetriever
except ImportError:
    pass

try:
    from .pattern_crystallizer import PatternCrystallizer
except ImportError:
    pass

try:
    from .reasoning_trace_manager import ReasoningTraceManager, ReasoningStep, ReasoningTrace
except ImportError:
    pass

try:
    from .sleep_adapter import SleepConsolidationAdapter
except ImportError:
    pass

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