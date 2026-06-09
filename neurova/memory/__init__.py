"""
Memory模块兼容性层

提供 neurova.memory 命名空间，实际实现在 neurova.cognitive_layers.memory_layer 中。
这是为了兼容现有测试代码中的导入语句。
"""

import sys
import importlib
import logging

logger = logging.getLogger(__name__)

# 从 neurova.cognitive_layers.memory_layer 重新导出主要类（全部用 try/except 保护 + 回退值）
try:
    from neurova.cognitive_layers.memory_layer import (
        MoEMemoryRouter,
        UnifiedVectorStore,
        ConflictDetector,
        TemperatureEngine,
        ConversationMemoryBuffer,
        SleepConsolidation,
        GraphTraversal,
    )
except ImportError as e:
    logger.debug(f"部分 cognitive_layers.memory_layer 导入失败: {e}")
    MoEMemoryRouter = None
    UnifiedVectorStore = None
    ConflictDetector = None
    TemperatureEngine = None
    ConversationMemoryBuffer = None
    SleepConsolidation = None
    GraphTraversal = None

# 可能不存在的类，用占位
try:
    from neurova.cognitive_layers.memory_layer.working_memory import WorkingMemoryAugmenter
except ImportError:
    WorkingMemoryAugmenter = None

try:
    from neurova.cognitive_layers.memory_layer.temporal_knowledge_graph import TemporalKnowledgeGraph
except ImportError:
    TemporalKnowledgeGraph = None

try:
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
except ImportError:
    MemoryStorage = None

try:
    from neurova.cognitive_layers.memory_layer.agent_self import SelfModel, AgentSelfManager
except ImportError:
    SelfModel = None
    AgentSelfManager = None

try:
    from neurova.cognitive_layers.memory_layer.agent_self import UserProfile
except ImportError:
    UserProfile = None

try:
    from neurova.cognitive_layers.memory_layer.compression import MemoryCompressor
except ImportError:
    MemoryCompressor = None

try:
    from neurova.cognitive_layers.memory_layer.vector_search import VectorSearch
except ImportError:
    VectorSearch = None

try:
    from neurova.cognitive_layers.memory_layer.proactive_recall import ProactiveRecall
except ImportError:
    ProactiveRecall = None

try:
    from neurova.cognitive_layers.memory_layer.proactive_question import ProactiveQuestion
except ImportError:
    ProactiveQuestion = None

try:
    from neurova.cognitive_layers.memory_layer.memory_stream import MemoryStream
except ImportError:
    MemoryStream = None

try:
    from neurova.cognitive_layers.memory_layer.version_control import VersionControl
except ImportError:
    VersionControl = None

try:
    from neurova.cognitive_layers.memory_layer.cache import MemoryCache
except ImportError:
    MemoryCache = None

try:
    from neurova.cognitive_layers.memory_layer.security import MemorySecurity
except ImportError:
    MemorySecurity = None

try:
    from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
except ImportError:
    ConversationBuffer = None

try:
    from neurova.mem_core import Memory
except ImportError:
    Memory = None

try:
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
except ImportError:
    MemoryManager = None

try:
    from neurova.cognitive_layers.memory_layer.meta_cognition import MetaCognition
except ImportError:
    MetaCognition = None

try:
    from neurova.cognitive_layers.memory_layer.models import MemoryCategory, MemoryType, LifecycleStage
except ImportError:
    MemoryCategory = None
    MemoryType = None
    LifecycleStage = None

try:
    from neurova.cognitive_layers.memory_layer.emotion import EmotionAnalyzer
except ImportError:
    EmotionAnalyzer = None

try:
    from neurova.cognitive_layers.emotion_context_layer.emotion import (
        EMOTION_KEYWORDS,
        EMOTION_WEIGHTS,
    )
except ImportError:
    EMOTION_KEYWORDS = {}
    EMOTION_WEIGHTS = {}

# 兼容性别名
ProactiveQuestionManager = ProactiveQuestion

# 为了支持 `from neurova.memory.xxx import ...` 这样的导入
_MODULE_MAP = {
    "working_memory": "neurova.cognitive_layers.memory_layer.working_memory",
    "temporal_knowledge_graph": "neurova.cognitive_layers.memory_layer.temporal_knowledge_graph",
    "storage": "neurova.cognitive_layers.memory_layer.storage",
    "models": "neurova.cognitive_layers.memory_layer.models",
    "temperature": "neurova.cognitive_layers.memory_layer.temperature",
    "sleep": "neurova.cognitive_layers.memory_layer.sleep",
    "compression": "neurova.cognitive_layers.memory_layer.compression",
    "vector_search": "neurova.cognitive_layers.memory_layer.vector_search",
    "proactive_recall": "neurova.cognitive_layers.memory_layer.proactive_recall",
    "proactive_question": "neurova.cognitive_layers.memory_layer.proactive_question",
    "agent_self": "neurova.cognitive_layers.memory_layer.agent_self",
    "conversation_buffer": "neurova.cognitive_layers.memory_layer.conversation_buffer",
    "memory_stream": "neurova.cognitive_layers.memory_layer.memory_stream",
    "conflict": "neurova.cognitive_layers.memory_layer.conflict",
    "version_control": "neurova.cognitive_layers.memory_layer.version_control",
    "cache": "neurova.cognitive_layers.memory_layer.cache",
    "security": "neurova.cognitive_layers.memory_layer.security",
}

for alias, target in _MODULE_MAP.items():
    try:
        sys.modules[__name__ + "." + alias] = importlib.import_module(target)
    except ImportError as _e:
        logger.debug(f"memory 子模块别名 {alias} -> {target} 映射失败: {_e}")

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
    "ConversationBuffer",
    "MemoryStream",
    "ConflictDetector",
    "VersionControl",
    "MemoryCache",
    "MemorySecurity",
    "MemoryManager",
    "MetaCognition",
    "MemoryCategory",
    "MemoryType",
    "LifecycleStage",
    "EmotionAnalyzer",
    "EMOTION_KEYWORDS",
    "EMOTION_WEIGHTS",
]
