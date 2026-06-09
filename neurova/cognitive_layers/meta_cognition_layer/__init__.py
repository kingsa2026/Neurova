"""
Meta Cognition Layer - 元认知层

实现 Neurova CogArch 1.0.0 的元认知层架构：
- 自我反思 (Self Reflection)
- 自我优化 (Self Optimization)
- 技能进化 (Skills Evolution)
- 成长日志 (Growth Log)
- 问题队列 (Question Queue)
- 自治系统 (Autonomy System)
- 宪法/基本指令 (Constitution)
...
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.agent_core import Agent
except ImportError as _e:
    _logger.debug(f"Agent 未可用: {_e}")
    Agent = None

try:
    from neurova.skills.models import Skill
except ImportError as _e:
    _logger.debug(f"Skill 未可用: {_e}")
    Skill = None

# cognitive_layers imports
try:
    import neurova.cognitive_layers.meta_cognition_layer.autonomy_system
except ImportError as _e:
    _logger.debug(f"autonomy_system 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.constitution
except ImportError as _e:
    _logger.debug(f"constitution 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.growth_log
except ImportError as _e:
    _logger.debug(f"growth_log 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.meta_cognition
except ImportError as _e:
    _logger.debug(f"meta_cognition 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.personality
except ImportError as _e:
    _logger.debug(f"personality 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.question_queue
except ImportError as _e:
    _logger.debug(f"question_queue 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.self_optimization
except ImportError as _e:
    _logger.debug(f"self_optimization 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.self_reflection
except ImportError as _e:
    _logger.debug(f"self_reflection 模块未可用: {_e}")

try:
    import neurova.cognitive_layers.meta_cognition_layer.skills_manager
except ImportError as _e:
    _logger.debug(f"skills_manager 模块未可用: {_e}")