"""
Neurova 协作模块

功能:
1. 项目隔离管理
2. 文件隔离管理
3. 工作流隔离管理
4. 团队成员管理
"""

from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager

# collaboration imports
import neurova.collaboration.collaboration_isolation

__all__ = ["CollaborationIsolationManager"]