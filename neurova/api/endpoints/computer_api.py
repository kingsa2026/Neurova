"""
Computer Management API Endpoints
"""

import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Depends, Request, status
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.models.computer import (
    Computer,
    ComputerEngine,
    ComputerKind,
    ComputerStatus,
)
from neurova.collaboration.computer_manager import (
    PAIR_TOKEN_TTL_SECONDS,
    get_computer_manager_singleton,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/computers", tags=["Computers"])


class ComputerPublic(BaseModel):
    """Computer 公开投影；任何凭据字段都不得进入。"""

    model_config = ConfigDict(from_attributes=True)

    computer_id: str
    name: str
    kind: ComputerKind
    engine: ComputerEngine
    status: ComputerStatus
    last_seen_at: Optional[float] = None
    owner_user_id: str
    company_id: str
    agents: Dict[str, Any] = Field(default_factory=dict)
    daemon_version: Optional[str] = None
    paired_at: Optional[float] = None
    revoked_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float
    deleted_at: Optional[float] = None


class ComputerPairRequest(BaseModel):
    pair_token: str = Field(min_length=1)
    host_name: str
    available_engines: List[str]
    daemon_version: str
    supervised: bool = False


class ComputerPairResponse(BaseModel):
    computer: ComputerPublic
    daemon_token: str


class PairTicketResponse(BaseModel):
    pair_token: str
    expires_in: int


def _currentUserId(identity: Dict[str, Any]) -> str:
    """从 JWT 身份字典取当前用户 id。"""
    return str(identity.get("user_id") or "").strip()


def _requireUserId(identity: Dict[str, Any]) -> str:
    uid = _currentUserId(identity)
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authenticated user required")
    return uid


def _publicComputer(computer: Computer) -> ComputerPublic:
    return ComputerPublic.model_validate(computer)


def _notFound(computer_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"Computer {computer_id} not found or access denied",
    )


# ============================================================================
# Computer CRUD Operations
# ============================================================================

@router.get("", response_model=List[ComputerPublic])
async def list_user_computers(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出当前用户的所有 Computers。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computers = manager.list_user_computers(uid)
        return [_publicComputer(computer) for computer in computers]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list computers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=ComputerPublic)
async def create_computer(
    name: str,
    kind: ComputerKind = ComputerKind.CLOUD,
    engine: ComputerEngine = ComputerEngine.MANAGED,
    company_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """创建新 Computer。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.create_computer(
            name=name,
            owner_user_id=uid,
            kind=kind,
            engine=engine,
            company_id=company_id or "",
        )
        if not computer:
            raise HTTPException(status_code=500, detail="Failed to create computer")

        logger.info(f"Created computer: {computer.computer_id} by {uid}")
        return _publicComputer(computer)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 静态路由必须先于 /{computer_id}，否则会被单设备详情首匹配吞掉。
# ============================================================================

@router.get("/admin/all", response_model=List[ComputerPublic])
async def admin_list_all_computers(
    include_deleted: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """管理员列出所有 Computers。"""
    uid = _requireUserId(current_user)
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Required role: admin",
        )
    try:
        manager = get_computer_manager_singleton()
        computers = manager.admin_list_all_computers(uid, include_deleted=include_deleted)
        return [_publicComputer(computer) for computer in computers]
    except Exception as e:
        logger.error(f"Failed to list all computers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cloud", response_model=ComputerPublic)
async def get_cloud_computer(
    company_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取 Cloud Computer 实例。"""
    try:
        _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.get_cloud_computer()
        if not computer:
            raise HTTPException(status_code=404, detail="No cloud computer available")
        return _publicComputer(computer)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cloud computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup-offline")
async def cleanup_offline_computers(
    timeout_minutes: int = 90,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """清理离线超过超时时间的 Computers（仅管理员）。"""
    _requireUserId(current_user)
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Required role: admin",
        )
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


# ============================================================================
# Owner-scoped single-computer operations
# ============================================================================

@router.get("/{computer_id}", response_model=ComputerPublic)
async def get_computer(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取指定 Computer。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.get_computer(computer_id, user_id=uid)
        if not computer:
            raise _notFound(computer_id)
        return _publicComputer(computer)
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
    """删除 Computer。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        result = manager.delete_computer(computer_id, hard=hard, user_id=uid)
        if not result:
            raise _notFound(computer_id)
        return {"success": True, "computer_id": computer_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# BYOA Pairing
# ============================================================================

@router.post("/{computer_id}/pair-token", response_model=PairTicketResponse)
async def issue_pair_token(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """属主签发短期一次性配对票据。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.get_computer(computer_id, user_id=uid)
        if not computer or computer.status == ComputerStatus.DELETED:
            raise _notFound(computer_id)
        pair_token = manager.issue_pair_token(computer_id, user_id=uid)
        if not pair_token:
            raise _notFound(computer_id)
        return PairTicketResponse(pair_token=pair_token, expires_in=PAIR_TOKEN_TTL_SECONDS)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to issue pairing ticket: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{computer_id}/pair", response_model=ComputerPairResponse)
async def pair_byoa_computer(
    computer_id: str,
    payload: ComputerPairRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """消费服务端签发的配对票据；daemon 凭据仅在本响应返回一次。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.get_computer(computer_id, user_id=uid)
        if not computer or computer.status == ComputerStatus.DELETED:
            raise _notFound(computer_id)

        paired = manager.pair_byoa_computer(
            computer_id=computer_id,
            user_id=uid,
            pair_token=payload.pair_token,
            host_name=payload.host_name,
            available_engines=payload.available_engines,
            daemon_version=payload.daemon_version,
            supervised=payload.supervised,
        )
        if not paired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="pairing ticket invalid, expired or already used",
            )

        logger.info(f"Paired BYOA computer: {computer_id}")
        return ComputerPairResponse(
            computer=_publicComputer(paired.computer),
            daemon_token=paired.daemon_token,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pair BYOA computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{computer_id}/revoke", response_model=ComputerPublic)
async def revoke_computer(
    computer_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """撤销 Computer 访问权限。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        result = manager.revoke_computer(computer_id, user_id=uid)
        if not result:
            raise _notFound(computer_id)

        logger.warning(f"Revoked computer: {computer_id}")
        computer = manager.get_computer(computer_id, user_id=uid)
        if not computer:
            raise _notFound(computer_id)
        return _publicComputer(computer)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke computer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Heartbeat & Status
# ============================================================================

def _verifyDaemonCredential(computer: Computer, presented: Optional[str]) -> None:
    """校验 daemon 凭据；服务端只存 SHA256 摘要，比较使用常量时间算法。"""
    stored = computer.daemon_token
    if not stored:
        raise HTTPException(
            status_code=401,
            detail="computer 未配对，无共享令牌可校验；请先完成 BYOA 配对",
        )
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="daemon credential required（Authorization: Bearer <token> 或 ?token=）",
        )
    digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    if not (hmac.compare_digest(digest, stored) or hmac.compare_digest(presented, stored)):
        raise HTTPException(status_code=401, detail="daemon credential mismatch")


@router.post("/{computer_id}/heartbeat")
async def heartbeat(
    computer_id: str,
    request: Request,
    version: Optional[str] = None,
):
    """接收 Computer heartbeat（daemon 上报，须携带配对共享令牌）。"""
    try:
        manager = get_computer_manager_singleton()
        computer = manager.get_computer(computer_id)
        if not computer:
            raise HTTPException(status_code=404, detail=f"Unknown computer: {computer_id}")

        auth_header = request.headers.get("authorization") or ""
        presented = None
        if auth_header.lower().startswith("bearer "):
            presented = auth_header[7:].strip()
        if not presented:
            presented = request.query_params.get("token")
        _verifyDaemonCredential(computer, presented)

        result = manager.heartbeat(computer_id, version=version)
        if not result:
            raise HTTPException(status_code=404, detail=f"Unknown computer: {computer_id}")
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
    """列出 Computer 上的所有 Agents。"""
    try:
        uid = _requireUserId(current_user)
        manager = get_computer_manager_singleton()
        computer = manager.get_computer(computer_id, user_id=uid)
        if not computer:
            raise _notFound(computer_id)
        return list(computer.agents.keys())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))
