"""
Memory模块兼容性层

提供 neurova.memory 命名空间，实际实现在 neurova.cognitive_layers.memory_layer 中。
这是为了兼容现有测试代码中的导入语句。
"""

import sys
import importlib

# 从 neurova.cognitive_layers.memory_layer 重新导出主要类
from neurova.cognitive_layers.memory_layer import (
    WorkingMemoryAugmenter,
    TemporalKnowledgeGraph,
    MemoryStorage,
    SelfModel,
    UserProfile,
    Memory,
    TemperatureEngine,
    SleepConsolidation,
    MemoryCompressor,
    VectorSearch,
    ProactiveRecall,
    ProactiveQuestion,
    AgentSelfManager,
    ConversationBuffer,
    MemoryStream,
    ConflictDetector,
    VersionControl as MemoryVersionControl,
    MemoryCache,
    MemorySecurity,
)
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.meta_cognition import MetaCognition
from neurova.cognitive_layers.memory_layer.models import MemoryCategory, MemoryType, LifecycleStage
from neurova.cognitive_layers.memory_layer.emotion import EmotionAnalyzer
from neurova.cognitive_layers.emotion_context_layer.emotion import (
    EMOTION_KEYWORDS,
    EMOTION_WEIGHTS
)

# 为了支持 `from neurova.memory.xxx import ...` 这样的导入
# 我们需要创建子模块引用
sys.modules[__name__ + ".working_memory"] = importlib.import_module("neurova.cognitive_layers.memory_layer.working_memory")
sys.modules[__name__ + ".temporal_knowledge_graph"] = importlib.import_module("neurova.cognitive_layers.memory_layer.temporal_knowledge_graph")
sys.modules[__name__ + ".storage"] = importlib.import_module("neurova.cognitive_layers.memory_layer.storage")
sys.modules[__name__ + ".models"] = importlib.import_module("neurova.cognitive_layers.memory_layer.models")
sys.modules[__name__ + ".temperature"] = importlib.import_module("neurova.cognitive_layers.memory_layer.temperature")
sys.modules[__name__ + ".sleep"] = importlib.import_module("neurova.cognitive_layers.memory_layer.sleep")
sys.modules[__name__ + ".compression"] = importlib.import_module("neurova.cognitive_layers.memory_layer.compression")
sys.modules[__name__ + ".vector_search"] = importlib.import_module("neurova.cognitive_layers.memory_layer.vector_search")
sys.modules[__name__ + ".proactive_recall"] = importlib.import_module("neurova.cognitive_layers.memory_layer.proactive_recall")
sys.modules[__name__ + ".proactive_question"] = importlib.import_module("neurova.cognitive_layers.memory_layer.proactive_question")
sys.modules[__name__ + ".agent_self"] = importlib.import_module("neurova.cognitive_layers.memory_layer.agent_self")
sys.modules[__name__ + ".conversation_buffer"] = importlib.import_module("neurova.cognitive_layers.memory_layer.conversation_buffer")
sys.modules[__name__ + ".memory_stream"] = importlib.import_module("neurova.cognitive_layers.memory_layer.memory_stream")
sys.modules[__name__ + ".conflict"] = importlib.import_module("neurova.cognitive_layers.memory_layer.conflict")
sys.modules[__name__ + ".version_control"] = importlib.import_module("neurova.cognitive_layers.memory_layer.version_control")
sys.modules[__name__ + ".cache"] = importlib.import_module("neurova.cognitive_layers.memory_layer.cache")
sys.modules[__name__ + ".security"] = importlib.import_module("neurova.cognitive_layers.memory_layer.security")

# 兼容性别名
ProactiveQuestionManager = ProactiveQuestion  # 为了兼容旧代码

__all__ = [
    "WorkingMemoryAugmenter",
    "TemporalKnowledgeGraph",
    "MemoryStorage",
    "SelfModel",
    "UserProfile",
    "Memory",
    "TemperatureEngine",
    "SleepConsolidation",
    "MemoryCompressor",
    "VectorSearch",
    "ProactiveRecall",
    "ProactiveQuestionManager",
    "AgentSelfManager",
    "ConversationBuffer",  # 实际类名
    "MemoryStream",
    "ConflictDetector",
    "MemoryVersionControl",
    "MemoryCache",
    "MemorySecurity",
    # 新增
    "MemoryManager",
    "MetaCognition",
    "MemoryCategory",
    "MemoryType",
    "LifecycleStage",
    "EmotionAnalyzer",
    "EMOTION_KEYWORDS",
    "EMOTION_WEIGHTS",
]
