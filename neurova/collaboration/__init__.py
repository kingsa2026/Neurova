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
    _logger.debug(f"CollaborationIsolationManager 未可用: {_e}")
    CollaborationIsolationManager = None

# collaboration imports
try:
    import neurova.collaboration.collaboration_isolation
except ImportError as _e:
    _logger.debug(f"collaboration.collaboration_isolation 模块未可用: {_e}")

__all__ = ["CollaborationIsolationManager"]