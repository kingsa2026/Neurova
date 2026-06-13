"""
进化模块 — 工具进化与闭环学习

提供工具进化、生命周期管理、权重自适应等功能。
包含递归自我进化（RSI）核心机制。
"""

import logging

_logger = logging.getLogger(__name__)

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
    # RSI模块
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
]
