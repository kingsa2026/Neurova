"""
Neurova 协作模块

功能:
1. 项目隔离管理
2. 文件隔离管理
3. 工作流隔离管理
4. 团队成员管理
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager
except ImportError as _e:
    _logger.debug("CollaborationIsolationManager 未可用: %s", _e)
    CollaborationIsolationManager = None

# collaboration imports
try:
    pass
except ImportError as _e:
    _logger.debug("collaboration.collaboration_isolation 模块未可用: %s", _e)

__all__ = ["CollaborationIsolationManager"]
