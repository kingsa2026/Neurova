"""
Memory模块兼容性层

提供 neurova.memory 命名空间，实际实现在 neurova.cognitive_layers.memory_layer 中。
这是为了兼容现有测试代码中的导入语句。
"""

import importlib
from neurova.core.logger import get_logger
import sys

logger = get_logger(__name__)

# 从 neurova.cognitive_layers.memory_layer 各子模块重新导出主要类。
# 此前每条都包着 `try/except ImportError: X = None`——本批拆掉之后立刻暴露出两条**一直在被吞**的
# 坏指路：聚合模块 `memory_layer` 并不导出 GraphTraversal / SleepConsolidation，名字其实在
# `.graph_traversal` / `.sleep` 里。旧形态下 `from neurova.memory import GraphTraversal` 拿到的是
# None 且不报错；改指真出处之后才拿得到真类（探针实证，见台账 §6-201）。
from neurova.cognitive_layers.memory_layer import ConflictDetector

from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer as ConversationMemoryBuffer

from neurova.cognitive_layers.memory_layer.graph_traversal import GraphTraversal

from neurova.cognitive_layers.memory_layer import MoEMemoryRouter

from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

from neurova.cognitive_layers.memory_layer import TemperatureEngine

from neurova.cognitive_layers.memory_layer import UnifiedVectorStore

# 其余子系统的再导出（这一组原先也各带一条 None 兜底；拆掉后全部指得通，注释随之改如实）
from neurova.cognitive_layers.memory_layer.working_memory import WorkingMemoryAugmenter

from neurova.cognitive_layers.memory_layer.temporal_knowledge_graph import TemporalKnowledgeGraph

from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

from neurova.cognitive_layers.memory_layer.agent_self import AgentSelfManager

from neurova.cognitive_layers.memory_layer.models import SelfModel, UserProfile

from neurova.cognitive_layers.memory_layer.compression import MemoryCompressor

from neurova.cognitive_layers.memory_layer.vector_search import VectorSearch

# `ProactiveQuestion` / `VersionControl` 这两个名字在仓内**没有实装**（真身分别是
# `proactive_question.Question`+`QuestionQueueManager` 与 `version_control.MemoryVersionControl`，
# 名字不同）。此前门面用 try/except 把它们降级成 None，谁都没发现；本批把坏指路摘掉而不是
# 猜一个别名顶上去——要不要以真名再导出＝另一次裁定（台账 §6-201）。

from neurova.cognitive_layers.memory_layer.memory_stream import MemoryStream

# `MemoryCache` 的再导出随本批摘掉，理由三条，逐条现读可核：
# ① `from neurova.memory import MemoryCache` 全仓零消费者（AST 数 ImportFrom(neurova.memory) 的
#    绑定名，命中 0）；
# ② 这条 import 与 `neurova/core/cache.py` 之间是**真循环**：`memory_layer/cache.py` 取
#    `neurova.core.cache`，后者取 `neurova.memory.core.cache`，取包名就回头执行本 `__init__`。
#    先 import 本门面时侥幸走通（探针实证 P1/P2/P3 三条都对），先 import
#    `neurova.cognitive_layers.memory_layer.cache`（`tests/unit/memory/test_cache_comprehensive.py`
#    就是这么写的）时(cache 半成品) 就撞回本行——**此前这条被 try/except 吞着，所以表现为
#    门面上 `MemoryCache = None` 而测试照样绿**，摘掉兜底后循环才第一次露出来（本批实测：
#    留着这行，那档测试直接 collection error）。
# ③ 缓存实现的单一出处是 `neurova.core.cache`。顺带登记一条双源（台账 §6-201）：仓里现在有三本
#    缓存账——`neurova/memory/core/cache.py`（实装）、`neurova/core/cache.py`（全局实例与再导出）、
#    `neurova/cognitive_layers/memory_layer/cache.py`（薄壳再导出）。三者要不要收成一条＝另一次裁定。
from neurova.cognitive_layers.memory_layer.security import MemorySecurity

from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer

from neurova.cognitive_layers.memory_layer.models import Memory

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

# memory_layer/meta_cognition.py 已删除（零调用方死代码，2026-08 清理）

from neurova.cognitive_layers.memory_layer.models import LifecycleStage, MemoryCategory, MemoryType

from neurova.cognitive_layers.memory_layer.emotion import EmotionAnalyzer

try:
    from neurova.cognitive_layers.emotion_context_layer.emotion import (
        EMOTION_KEYWORDS,
        EMOTION_WEIGHTS,
    )
except ImportError:
    EMOTION_KEYWORDS = {}
    EMOTION_WEIGHTS = {}

# 兼容性别名（`ProactiveQuestionManager = ProactiveQuestion` 这一条随上面坏指路一起摘除：
# 右边那个名字在仓内没有实装，旧形态下它是 None，于是这个别名也是 None，没人发现）

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
        logger.debug("memory 子模块别名 %s -> %s 映射失败: %s", alias, target, _e)

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
    "AgentSelfManager",
    "ConversationBuffer",
    "MemoryStream",
    "ConflictDetector",
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
