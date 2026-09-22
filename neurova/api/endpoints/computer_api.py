"""
Computer Management API Endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import Any, Dict, List, Optional
from datetime import datetime

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.models.computer import (
    Computer,
    ComputerKind,
    ComputerEngine,
)
from neurova.collaboration.computer_manager import (
    get_computer_manager_singleton,
)
from neurova.models.cost_tracking import (
    CostTracker,
    LLMCall,
    LLMProvider,
    LLMDirection,
    get_cost_tracker,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/computers", tags=["Computers"])


def _currentUserId(identity: Dict[str, Any]) -> str:
    """从 JWT 身份字典取当前用户 id（与全库其它端点同一形态）。

    原先这里是 `Depends(lambda: "current_user")` —— 硬编码常量身份，
    等于把「谁在调用」当成不可避免的未知。挂载之前必须先有真身份，
    否则接上去就是把计算节点数据对匿名请求开放。
    """
    return str(identity.get("user_id") or "")



# ============================================================================
# Computer CRUD Operations
# ============================================================================

@router.get("", response_model=List[Computer])
async def list_user_computers(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    列出当前用户的所有 Computers

    - **user_id**: 当前用户 ID (从认证上下文获取)

    Returns all computers owned by the current user.
    """
    try:
        manager = get_computer_manager_singleton()
        computers = manager.list_user_computers(_currentUserId(current_user))

        return computers

    except Exception as e:
        logger.error(f"Failed to list computers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("", response_model=Computer)
async def create_computer(
    name: str,
    kind: ComputerKind = ComputerKind.CLOUD,
    engine: ComputerEngine = ComputerEngine.MANAGED,
    company_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    创建新 Computer

    - **name**: Computer 名称
    - **kind**: 类型 (cloud/local/vps)
    - **engine**: 引擎类型 (managed/claude/codex/etc)
    - **company_id**: 所属公司 ID (可选)
    """
    try:
        manager = get_computer_manager_singleton()

        computer = manager.create_computer(
            name=name,
            owner_user_id=_currentUserId(current_user),
            kind=kind,
            engine=engine,
            company_id=company_id or "",
        )

        if not computer:
            raise HTTPException(status_code=500, detail="Failed to create computer")

        logger.info(f"Created computer: {computer.computer_id} by {_currentUserId(current_user)}")
        return computer

    except Exception as e:
        logger.error(f"Failed to create computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{computer_id}", response_model=Computer)
async def get_computer(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取指定 Computer

    - **computer_id**: Computer ID
    """
    try:
        manager = get_computer_manager_singleton()

        computer = manager.get_computer(computer_id, user_id=_currentUserId(current_user))

        if not computer:
            raise HTTPException(
                status_code=404,
                detail=f"Computer {computer_id} not found or access denied"
            )

        return computer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{computer_id}", response_model=dict)
async def delete_computer(
    computer_id: str,
    hard: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    删除 Computer

    - **computer_id**: Computer ID
    - **hard**: 硬删除 vs 软删除
    """
    try:
        manager = get_computer_manager_singleton()

        result = manager.delete_computer(computer_id, hard=hard)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Computer {computer_id} not found"
            )

        return {"success": True, "computer_id": computer_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# BYOA Pairing
# ============================================================================

@router.post("/{computer_id}/pair", response_model=Computer)
async def pair_byoa_computer(
    computer_id: str,
    pair_token: str,
    host_name: str,
    available_engines: List[str],
    daemon_version: str,
    supervised: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    BYOA Computer 配对

    - **computer_id**: Computer ID
    - **pair_token**: 配对 token (device credential)
    - **host_name**: 主机名
    - **available_engines**: 可用引擎列表
    - **daemon_version**: daemon 版本
    - **supervised**: 是否作为服务运行
    """
    try:
        manager = get_computer_manager_singleton()

        computer = manager.pair_byoa_computer(
            computer_id=computer_id,
            pair_token=pair_token,
            host_name=host_name,
            available_engines=available_engines,
            daemon_version=daemon_version,
            supervised=supervised,
        )

        if not computer:
            raise HTTPException(
                status_code=404,
                detail=f"Computer {computer_id} not found"
            )

        logger.info(f"Paired BYOA computer: {computer_id}")
        return computer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pair BYOA computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{computer_id}/revoke", response_model=Computer)
async def revoke_computer(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    撤销 Computer 访问权限

    - **computer_id**: Computer ID
    """
    try:
        manager = get_computer_manager_singleton()

        result = manager.revoke_computer(computer_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Computer {computer_id} not found"
            )

        logger.warning(f"Revoked computer: {computer_id}")
        return manager.get_computer(computer_id, user_id=_currentUserId(current_user))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Heartbeat & Status
# ============================================================================

@router.post("/{computer_id}/heartbeat")
async def heartbeat(
    computer_id: str,
    version: Optional[str] = None,
):
    """
    接收 Computer heartbeat

    - **computer_id**: Computer ID
    - **version**: daemon 版本
    """
    try:
        manager = get_computer_manager_singleton()

        result = manager.heartbeat(computer_id, version=version)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown computer: {computer_id}"
            )

        return {"status": "ok", "computer_id": computer_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process heartbeat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{computer_id}/agents", response_model=List[str])
async def list_agents_on_computer(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    列出 Computer 上的所有 Agents

    - **computer_id**: Computer ID
    """
    try:
        manager = get_computer_manager_singleton()

        computer = manager.get_computer(computer_id, user_id=_currentUserId(current_user))

        if not computer:
            raise HTTPException(
                status_code=404,
                detail=f"Computer {computer_id} not found"
            )

        return list(computer.agents.keys())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Admin Operations
# ============================================================================

@router.get("/admin/all", response_model=List[Computer])
async def admin_list_all_computers(
    include_deleted: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    管理员列出所有 Computers

    - **include_deleted**: 是否包含已删除
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Required role: admin",
        )
    try:
        manager = get_computer_manager_singleton()

        computers = manager.admin_list_all_computers(
            _currentUserId(current_user), include_deleted=include_deleted
        )

        return computers

    except Exception as e:
        logger.error(f"Failed to list all computers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Cloud Computer
# ============================================================================

@router.get("/cloud", response_model=Computer)
async def get_cloud_computer(
    company_id: Optional[str] = None,
):
    """
    获取 Cloud Computer 实例

    - **company_id**: 公司 ID (可选，用于过滤)
    """
    try:
        manager = get_computer_manager_singleton()

        computer = manager.get_cloud_computer()

        if not computer:
            raise HTTPException(
                status_code=404,
                detail="No cloud computer available"
            )

        return computer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cloud computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Cleanup
# ============================================================================

@router.post("/cleanup-offline")
async def cleanup_offline_computers(
    timeout_minutes: int = 90,
):
    """
    清理离线超过超时时间的 Computers

    - **timeout_minutes**: 超时时间 (分钟)
    """
    try:
        manager = get_computer_manager_singleton()

        cleaned_count = manager.cleanup_offline_computers(
            timeout_seconds=timeout_minutes * 60
        )

        logger.info(f"Cleaned up {cleaned_count} offline computers")

        return {"cleaned_count": cleaned_count}

    except Exception as e:
        logger.error(f"Failed to cleanup offline computers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
