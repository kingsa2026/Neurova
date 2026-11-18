# -*- coding: utf-8 -*-
"""记忆版本接口 — 版本列表与回滚（K3 断点闭环）

背景：`MemoryVersionControl` 自装配（`agent_core.wire_memory_guards`）以来只有
写入口——`post_chat_pipeline._step_version_snapshot` 每轮为召回记忆落「会话前
版本快照（可回滚保障）」，快照持续积累；而 `rollback_to_version` 全仓零生产
调用、零暴露，回滚能力用户永不可达（只写不读，断点）。

本模块是版本面的**读 + 回滚出口**：
- GET  /{memory_id}/versions  版本历史（最新在前）
- POST /{memory_id}/rollback  回滚到指定版本

鉴权：router 级 `requireIdentityForMemoryFace`（base.py 一处挂门）保证「有凭证」；
归属门沿用记忆面既有谓词——本人作用域 `manager.get_memory(agent_wide=False)`，
跨用户特权只认 `agentWidePrivilege`（与 `deps.require_admin()` 同规则的单源判定），
不另造第二套鉴权。

回滚语义沿用 `rollback_to_version` 既有实现：**新建 ROLLBACK 快照表达回滚，
不物理改写历史**（原版本仍可追溯）；本端点在此之上把活记忆内容同步回目标
版本——只记一行 ROLLBACK 而活记忆不变，不算回滚到位。
回滚是敏感操作：审计走 `security/audit_logger` 既有单源（S8 审批审计同款接法：
审计失败只告警，不阻断主流程），不新造审计写点。
"""

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.cognitive_layers.memory_layer.version_control import VersionType
from neurova.interfaces.api_standard import APIError, ErrorCodes, success_response

from .base import (
    _get_request_id,
    agentWidePrivilege,
    get_memory_manager,
    logger,
    memory_to_dict,
    router,
)


class MemoryRollbackRequest(BaseModel):
    """回滚请求体"""

    target_version: str = Field(..., min_length=1, description="目标版本 ID（GET /versions 可查）")
    reason: Optional[str] = Field(default=None, max_length=500, description="回滚原因（入审计）")


def _resolveMemoryScope(manager, memory_id: str, user: Dict[str, Any]):
    """owner/admin 归属门（读侧单点）。

    本人作用域读得到即 owner；读不到且请求方是管理员，按管理口径
    （agent_wide）再读一次——两读都空才 404（视同不存在，不给按 id
    探测他人记录的入口，与 get_memory 的 P1-6 口径一致）。
    返回 (memory, agentWide)，agentWide 供写侧 `update_memory` 同口径放行。
    """
    agentWide = False
    memory = manager.get_memory(memory_id, agent_wide=False)
    if memory is None and agentWidePrivilege(user):
        agentWide = True
        memory = manager.get_memory(memory_id, agent_wide=True)
    if memory is None:
        raise APIError.not_found(f"记忆不存在: {memory_id}") from None
    return memory, agentWide


def _getVersionControl(agent_id: Optional[str]):
    """取 agent 上的 version_control（装配点 `agent_core.wire_memory_guards`）。

    组件未装配是**状态未就绪**（503），不是操作失败——与 base.get_memory_manager
    对记忆子系统缺席的语义分级同款。
    """
    from neurova.api.app import get_app_state

    state = get_app_state()
    if not state:
        raise APIError(ErrorCodes.AGENT_NOT_INITIALIZED, "应用状态未初始化") from None
    agent = state.agents.get(agent_id) if agent_id else state.get_agent()
    if not agent:
        raise APIError(ErrorCodes.AGENT_NOT_INITIALIZED, f"Agent 不存在: {agent_id}") from None
    version_control = getattr(agent, "version_control", None)
    if version_control is None:
        raise APIError(ErrorCodes.AGENT_NOT_READY, "版本控制组件未装配") from None
    return version_control


def _writeRollbackAudit(
    memory_id: str,
    target_version: str,
    rolled,
    user: Dict[str, Any],
    req: Optional[Request],
) -> None:
    """回滚审计：复用 security/audit_logger 单源（S8 审批审计同款接法）。"""
    try:
        from neurova.security.audit_logger import (
            AuditEventType,
            AuditLogEntry,
            AuditSeverity,
            get_audit_logger,
        )

        get_audit_logger().log(
            AuditLogEntry(
                event_type=AuditEventType.SECURITY_EVENT,
                severity=AuditSeverity.HIGH,
                user_id=str((user or {}).get("user_id") or (user or {}).get("neuser_id") or ""),
                action="memory_rollback",
                details={
                    "target_version": target_version,
                    "rollback_version_id": rolled.version_id,
                    "reason": str(getattr(rolled, "description", "") or ""),
                    "content_chars": len(rolled.content or ""),
                },
                resource_type="memory",
                resource_id=memory_id,
                ip_address=req.client.host if (req is not None and req.client) else "",
                user_agent=(req.headers.get("user-agent", "") if req is not None else ""),
            )
        )
    except Exception as exc:  # noqa: BLE001 - 审计失败不阻断回滚主流程
        logger.warning("记忆回滚审计写入失败: %s", exc)


@router.get("/{memory_id}/versions", summary="记忆版本列表")
async def list_memory_versions(
    memory_id: str,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数上限"),
    version_type: Optional[str] = Query(
        default=None, description="按版本类型过滤 (snapshot/delta/rollback/merge)"
    ),
    req: Request = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """读取一条记忆的版本历史（最新在前，含会话前快照与回滚点）。"""
    if version_type is not None and version_type not in {t.value for t in VersionType}:
        raise HTTPException(status_code=422, detail=f"非法 version_type: {version_type}")
    try:
        manager = get_memory_manager(agent_id, user)
        _resolveMemoryScope(manager, memory_id, user)
        version_control = _getVersionControl(agent_id)
        type_filter = VersionType(version_type) if version_type else None
        versions = version_control.get_version_history(
            memory_id, limit=limit, version_type=type_filter
        )
        return success_response(
            data={
                "memory_id": memory_id,
                "count": len(versions),
                "versions": [v.to_dict() for v in versions],
            },
            message=f"共 {len(versions)} 个版本",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记忆版本列表读取失败: %s", e)
        raise APIError.internal(f"记忆版本列表读取失败: {str(e)}") from e


@router.post("/{memory_id}/rollback", summary="回滚记忆到指定版本")
async def rollback_memory_version(
    memory_id: str,
    body: MemoryRollbackRequest,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    req: Request = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """把记忆回滚到 target_version。

    活记忆内容恢复为该版本内容，并追加一行 ROLLBACK 快照（历史不物理改写，
    原版本仍可追溯）。目标版本不存在或不属于这条记忆一律 404（不泄露其他
    记忆的版本存在性）。敏感操作，落审计。
    """
    try:
        manager = get_memory_manager(agent_id, user)
        _, agentWide = _resolveMemoryScope(manager, memory_id, user)
        version_control = _getVersionControl(agent_id)

        target = version_control.get_version(body.target_version)
        if target is None or target.memory_id != memory_id:
            raise APIError.not_found(f"目标版本不存在: {body.target_version}") from None

        rolled = version_control.rollback_to_version(body.target_version)
        if rolled is None:
            raise APIError.internal("回滚失败：目标版本不可用") from None

        # 活记忆内容同步回目标版本（agentWide 是上面归属门定的口径，原样
        # 透传给 manager 的同一条归属校验）
        if not manager.update_memory(memory_id, agent_wide=agentWide, content=target.content):
            raise APIError.not_found(f"记忆不存在: {memory_id}") from None

        _writeRollbackAudit(memory_id, body.target_version, rolled, user, req)

        updated = manager.get_memory(memory_id, agent_wide=agentWide)
        return success_response(
            data={
                "memory_id": memory_id,
                "target_version_id": body.target_version,
                "rollback_version": rolled.to_dict(),
                "memory": memory_to_dict(updated, owned=True) if updated else None,
            },
            message=f"已回滚到版本 {body.target_version}",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记忆回滚失败: %s", e)
        raise APIError.internal(f"记忆回滚失败: {str(e)}") from e
