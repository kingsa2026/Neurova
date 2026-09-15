"""项目归属判定单源（B0/B1 画布与工作流共用）。

语义（对齐 neurflow storage P0-1 属主判定 + KB 可见性 fail-closed 先例）：
- default（桌面首启/未认证）放行创建期归属标记；
- 真实用户需项目成员关系（manager.get_project 权限语义）；
- manager 不可用 → fail-closed（非 default 一律 False）。
"""
from __future__ import annotations

import logging
from typing import Set

logger = logging.getLogger(__name__)


def _manager():
    try:
        from neurova.collaboration.collaboration_isolation import get_collaboration_manager

        if get_collaboration_manager is None:
            return None
        return get_collaboration_manager()
    except Exception:  # noqa: BLE001 - 协作服务缺失时按无项目降级
        return None


def requester_project_ids(user_id: str) -> Set[str]:
    """请求者参与的项目 id 集合（列表视图成员可读面）。"""
    if not user_id or user_id == "default":
        return set()
    mgr = _manager()
    if mgr is None:
        return set()
    try:
        return {p.project_id for p in (mgr.list_user_projects(user_id) or [])}
    except Exception:  # noqa: BLE001
        logger.debug("解析用户项目集合失败: %s", user_id, exc_info=True)
        return set()


def is_project_member(user_id: str, project_id: str) -> bool:
    """创建/改归属时的成员校验（default 放行）。"""
    if user_id == "default":
        return True
    mgr = _manager()
    if mgr is None:
        return False
    try:
        return mgr.get_project(project_id, user_id=user_id) is not None
    except Exception:  # noqa: BLE001
        return False
