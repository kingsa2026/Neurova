"""
进化模块 — 工具进化与闭环学习

提供工具进化、生命周期管理、权重自适应等功能。
包含递归自我进化（RSI）核心机制。
"""

from .closed_loop import (
    EvolutionOrchestrator,
    ToolLifecycleManager,
    AdaptiveToolWeights,
    PatternMiner,
    ToolGeneticEngine,
    NLToolSynthesizer,
)

# RSI模块（递归自我进化）
from .rsi import (
    RecursiveRatchetPruner,
    EnhancedRatchetPruner,
    Candidate,
)

__all__ = [
    # 核心进化模块
    "EvolutionOrchestrator",
    "ToolLifecycleManager",
    "AdaptiveToolWeights",
    "PatternMiner",
    "ToolGeneticEngine",
    "NLToolSynthesizer",
    # RSI模块
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
]
