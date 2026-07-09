"""
Cognitive Module - 认知模块

实现Neurova Skill系统2.0的认知编排功能。
包括认知状态管理、注意力管理、记忆管理和认知编排器。
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from neurova.cognitive_layers.memory_layer.models import Memory
except ImportError as _e:
    _logger.debug("Memory 未可用: %s", _e)
    Memory = None

# cognitive imports
try:
    pass
except ImportError as _e:
    _logger.debug("cognitive.orchestrator 模块未可用: %s", _e)
