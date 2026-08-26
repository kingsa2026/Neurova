"""
进化模块 — 工具进化与闭环学习

提供工具进化、生命周期管理、权重自适应等功能。
包含递归自我进化（RSI）核心机制。
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

# 核心进化模块
try:
    from .closed_loop import (
        AdaptiveToolWeights,
        EvolutionOrchestrator,
        PatternMiner,
        ToolGeneticEngine,
        ToolLifecycleManager,
        get_evolution_orchestrator,
        reset_evolution_orchestrator,
    )
except Exception as _e:
    # 修复 P0-9 (H2): ImportError → Exception，覆盖运行时错误；debug → warning
    _logger.warning("closed_loop 模块加载失败: %s", _e)
    EvolutionOrchestrator = None
    ToolLifecycleManager = None
    AdaptiveToolWeights = None
    PatternMiner = None
    ToolGeneticEngine = None
    get_evolution_orchestrator = None
    reset_evolution_orchestrator = None

# P0-B3 修复：导入真实的 NLToolSynthesizer（nl_synthesizer.py，502 行完整实现）
# 之前 __init__.py 从 closed_loop.py 导入同名占位符（10 行 stub），
# 导致 agent_core.py 拿到的是 stub，调用 pattern_miner kwarg 时虽然能构造，
# 但缺少 synthesize/suggest_tool_sequence 等真实方法。
try:
    from .nl_synthesizer import NLToolSynthesizer
except Exception as _e:
    _logger.warning("nl_synthesizer 模块加载失败: %s", _e)
    NLToolSynthesizer = None

# 事件驱动闭环（event_driven.py 已删除：零调用方死代码，2026-08 清理）

# RSI模块（递归自我进化）
try:
    from .rsi import (
        Candidate,
        EnhancedRatchetPruner,
        RecursiveRatchetPruner,
    )
except Exception as _e:
    # 修复 P0-9 (H2): ImportError → Exception
    _logger.warning("rsi 模块加载失败: %s", _e)
    RecursiveRatchetPruner = None
    EnhancedRatchetPruner = None
    Candidate = None

# 技能自动构建（修复 P0-8/P0-9: 新增导出，配合 agent_core.py 的 AutoSkillBuilder 初始化）
try:
    from .skill_encapsulation import (
        AutoSkillBuilder,
    )
except Exception as _e:
    # 修复 P0-9 (H2): ImportError → Exception
    _logger.warning("skill_encapsulation 模块加载失败: %s", _e)
    AutoSkillBuilder = None

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
    # RSI模块
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
    # 技能自动构建（修复 P0-8/P0-9）
    "AutoSkillBuilder",
]
