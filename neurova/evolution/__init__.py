"""
进化模块 — 工具进化与闭环学习

提供工具进化、生命周期管理、权重自适应等功能。
"""

from .closed_loop import (
    EvolutionOrchestrator,
    ToolLifecycleManager,
    AdaptiveToolWeights,
    PatternMiner,
    ToolGeneticEngine,
    NLToolSynthesizer,
)

__all__ = [
    "EvolutionOrchestrator",
    "ToolLifecycleManager",
    "AdaptiveToolWeights",
    "PatternMiner",
    "ToolGeneticEngine",
    "NLToolSynthesizer",
]
