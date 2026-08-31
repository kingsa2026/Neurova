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
    from .moe_router import ExpertDrilldownRetriever, MoEMemoryRouter, VectorGatingNetwork
except ImportError as _e:
    _mem_layer_logger.debug("moe_router 未可用: %s", _e)

try:
    from .unified_vector_store import UnifiedVectorStore
except ImportError as _e:
    _mem_layer_logger.debug("unified_vector_store 未可用: %s", _e)

try:
    from .models import LifecycleStage, MemoryCategory, MemoryType
except ImportError as _e:
    _mem_layer_logger.debug("models 未可用: %s", _e)

try:
    from .conflict_detector_v2 import ConflictDetector
except ImportError as _e:
    _mem_layer_logger.debug("conflict_detector_v2 未可用: %s", _e)

try:
    from .temperature import TemperatureEngine
except ImportError as _e:
    _mem_layer_logger.debug("temperature 未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _mem_layer_logger.debug("conversation_buffer 未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _mem_layer_logger.debug("sleep 未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _mem_layer_logger.debug("graph_traversal 未可用: %s", _e)

# 认知图谱存储架构 — 一步到位替换
try:
    from .cognitive_storage_engine import (
        CognitiveStorageEngine,
    )
    from .cognitive_storage_engine import MemoryType as CognitiveMemoryType
    from .cognitive_storage_engine import (
        StorageLayer,
        UnifiedMemoryNode,
    )
except ImportError as _e:
    _mem_layer_logger.debug("cognitive_storage_engine 未可用: %s", _e)

try:
    from .unified_retriever import UnifiedRetriever
except ImportError as _e:
    _mem_layer_logger.debug("unified_retriever 未可用: %s", _e)

try:
    from .pattern_crystallizer import PatternCrystallizer
except ImportError as _e:
    _mem_layer_logger.debug("pattern_crystallizer 未可用: %s", _e)

try:
    from .reasoning_trace_manager import ReasoningStep, ReasoningTrace, ReasoningTraceManager
except ImportError as _e:
    _mem_layer_logger.debug("reasoning_trace_manager 未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _mem_layer_logger.debug("sleep_adapter 未可用: %s", _e)

try:
    from .causal_reasoning import CausalReasoningEngine, get_causal_reasoning_engine
except ImportError as _e:
    _mem_layer_logger.debug("causal_reasoning 未可用: %s", _e)

try:
    from .question_decomposer import QuestionDecomposer, QuestionType, get_question_decomposer
except ImportError as _e:
    _mem_layer_logger.debug("question_decomposer 未可用: %s", _e)

try:
    from .neurova_recall import IntentAwareRecallStrategy, QueryIntent, QueryIntentDetector
except ImportError as _e:
    _mem_layer_logger.debug("neurova_recall intent classes 未可用: %s", _e)

# NeRF 记忆系统升级模块
try:
    from .positional_encoding import (
        EmotionPositionalEncoder,
        ImportancePositionalEncoder,
        PositionalEncoder,
        PositionalEncodingConfig,
        TemporalPositionalEncoder,
        create_emotion_encoder,
        create_importance_encoder,
        create_temporal_encoder,
    )
except ImportError as _e:
    _mem_layer_logger.debug("positional_encoding 未可用: %s", _e)

try:
    from .memory_field import (
        MemoryFieldConfig,
        MemoryFieldNetwork,
        MemoryFieldTrainer,
        get_memory_field,
        reset_memory_field,
    )
except ImportError as _e:
    _mem_layer_logger.debug("memory_field 未可用 (需要 torch): %s", _e)

try:
    from .volume_renderer import (
        ChannelSample,
        RenderedMemory,
        VolumeRenderer,
        create_volume_renderer,
        get_volume_renderer,
    )
except ImportError as _e:
    _mem_layer_logger.debug("volume_renderer 未可用: %s", _e)

# 版本信息
__version__ = "1.0.0"
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
    # 图能力增强模块
    "CausalReasoningEngine",
    "get_causal_reasoning_engine",
    "QuestionDecomposer",
    "QuestionType",
    "get_question_decomposer",
    # 意图感知检索模块
    "QueryIntent",
    "QueryIntentDetector",
    "IntentAwareRecallStrategy",
    # NeRF 记忆系统升级模块
    "PositionalEncodingConfig",
    "PositionalEncoder",
    "TemporalPositionalEncoder",
    "EmotionPositionalEncoder",
    "ImportancePositionalEncoder",
    "create_temporal_encoder",
    "create_emotion_encoder",
    "create_importance_encoder",
    "MemoryFieldConfig",
    "MemoryFieldNetwork",
    "MemoryFieldTrainer",
    "get_memory_field",
    "reset_memory_field",
    "ChannelSample",
    "RenderedMemory",
    "VolumeRenderer",
    "create_volume_renderer",
    "get_volume_renderer",
]

# 上面的 NeRF 系列模块（memory_field / volume_renderer / positional_encoding 等）
# 都包在 try/except ImportError 中：依赖缺失时对应名字根本不会绑定到本模块。
# 若 __all__ 仍声明这些名字，`from ... import *` 会抛
# AttributeError: module has no attribute 'xxx'。这里按实际可用情况裁剪。
__all__ = [name for name in __all__ if name in globals()]
