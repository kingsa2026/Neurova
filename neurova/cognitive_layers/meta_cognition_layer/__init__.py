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

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

def __getattr__(name: str):
    """PEP 562 惰性导出：延迟导入 agent_core / skills。

    原实现顶层 ``from neurova.agent_core import Agent`` 会形成循环导入环：
        agent_core -> context -> injector -> meta_cognition_layer -> agent_core
    导入 agent_core 时，meta_cognition_layer 回引尚未初始化完成的 agent_core，
    触发 ``cannot import name 'Agent' from partially initialized module``，
    导致 Agent=None 且每次导入刷屏 DEBUG。改为惰性导出后，仅在外部显式访问
    ``.Agent``/``.Skill`` 时才触发导入，彻底断开循环导入环。
    """
    if name == "Agent":
        from neurova.agent_core import Agent
        return Agent
    if name == "Skill":
        from neurova.skills.models import Skill
        return Skill
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# cognitive_layers imports
try:
    pass
except ImportError as _e:
    _logger.debug("autonomy_system 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("constitution 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("growth_log 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("meta_cognition 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("personality 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("question_queue 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("self_optimization 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("self_reflection 模块未可用: %s", _e)

try:
    pass
except ImportError as _e:
    _logger.debug("skills_manager 模块未可用: %s", _e)
