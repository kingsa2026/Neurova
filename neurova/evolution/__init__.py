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
        NLToolSynthesizer,
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
except Exception as _e:
    # 修复 P0-9 (H2): ImportError → Exception
    _logger.warning("event_driven 模块加载失败: %s", _e)
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
    "EvolutionEventBridge",
    "EvolutionEvent",
    "get_evolution_event_bridge",
    "reset_evolution_event_bridge",
    # RSI模块
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
    # 技能自动构建（修复 P0-8/P0-9）
    "AutoSkillBuilder",
]
