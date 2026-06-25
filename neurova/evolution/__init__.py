"""
进化模块 — 工具进化与闭环学习

提供工具进化、生命周期管理、权重自适应等功能。
包含递归自我进化（RSI）核心机制。
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from .closed_loop import (
        AdaptiveToolWeights,
        EvolutionOrchestrator,
        NLToolSynthesizer,
        PatternMiner,
        ToolGeneticEngine,
        ToolLifecycleManager,
        get_evolution_orchestrator,
        reset_evolution_orchestrator,
    )
except ImportError as _e:
    _logger.debug("closed_loop 模块未可用: %s", _e)
    EvolutionOrchestrator = None
    ToolLifecycleManager = None
    AdaptiveToolWeights = None
    PatternMiner = None
    ToolGeneticEngine = None
    NLToolSynthesizer = None
    get_evolution_orchestrator = None
    reset_evolution_orchestrator = None

# 事件驱动闭环
try:
    from .event_driven import (
        EvolutionEventBridge,
        EvolutionEvent,
        get_evolution_event_bridge,
        reset_evolution_event_bridge,
    )
except ImportError as _e:
    _logger.debug("event_driven 模块未可用: %s", _e)
    EvolutionEventBridge = None
    EvolutionEvent = None
    get_evolution_event_bridge = None
    reset_evolution_event_bridge = None

# RSI模块（递归自我进化）
try:
    from .rsi import (
        Candidate,
        EnhancedRatchetPruner,
        RecursiveRatchetPruner,
    )
except ImportError as _e:
    _logger.debug("rsi 模块未可用: %s", _e)
    RecursiveRatchetPruner = None
    EnhancedRatchetPruner = None
    Candidate = None

__all__ = [
    # 核心进化模块
    "EvolutionOrchestrator",
    "ToolLifecycleManager",
    "AdaptiveToolWeights",
    "PatternMiner",
    "ToolGeneticEngine",
    "NLToolSynthesizer",
    "get_evolution_orchestrator",
    "reset_evolution_orchestrator",
    # 事件驱动闭环
    "EvolutionEventBridge",
    "EvolutionEvent",
    "get_evolution_event_bridge",
    "reset_evolution_event_bridge",
    # RSI模块
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
]
