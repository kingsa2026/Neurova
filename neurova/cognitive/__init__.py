"""
Cognitive Module - 认知模块

实现Neurova Skill系统2.0的认知编排功能。
包括认知状态管理、注意力管理、记忆管理和认知编排器。
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.mem_core import Memory
except ImportError as _e:
    _logger.debug(f"Memory 未可用: {_e}")
    Memory = None

# cognitive imports
try:
    import neurova.cognitive.orchestrator
except ImportError as _e:
    _logger.debug(f"cognitive.orchestrator 模块未可用: {_e}")