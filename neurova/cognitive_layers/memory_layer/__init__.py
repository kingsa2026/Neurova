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

# 版本信息
__version__ = "0.1.0"
__all__ = [
    "MoEMemoryRouter",
    "VectorGatingNetwork", 
    "ExpertDrilldownRetriever",
    "UnifiedVectorStore",
    "MemoryCategory",
    "MemoryType",
    "LifecycleStage",
    "ConflictDetector",
]