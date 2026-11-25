# -*- coding: utf-8 -*-
"""检查点恢复面（K1：P1-5 检查点子系统的"能恢复"半条链接通）。

此前只有写入半条链（chat_pipeline._auto_checkpoint → CheckpointService），
恢复侧生产调用为零。本面补上两个端点：

- GET  /api/v1/agents/{agent_id}/checkpoints?session_id=...
    列出快照 refs，按 auto / snap / pre-restore 分组，含时间戳与说明；
- POST /api/v1/agents/{agent_id}/checkpoints/{ref}/restore
    事务化恢复（restore_with_rollback：恢复前自动留档 pre-restore，
    apply 失败自动回滚到恢复前状态）。恢复是敏感操作：请求体须带
    {"confirm": true} 显式确认，并落 security/audit_logger 审计
    （fail-open，审计失败不阻断恢复）。

鉴权沿用 agent_access 单源判定（requireAgentOwner：admin 全量 / 属主 /
无主仅 admin），不另造门。恢复写回经 session_manager 既有公开写口
（delete_session + save_message）重建会话历史，并同步运行中 agent 的
内存镜像（conversation_history / _conversation_context）——只回滚盘上
不回滚内存，下一轮上下文仍会带着"未来"的消息。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as FastAPIPath
from pydantic import BaseModel

from neurova.api.agent_access import requireAgentOwner
from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# kind → JSON 分组键（pre-restore 含 '-'，转成 pre_restore 作响应键）
_GROUP_KEYS = {"auto": "auto", "snap": "snap", "pre-restore": "pre_restore"}

# kind → 人类可读说明（列表面展示用）
_KIND_LABELS = {
    "auto": "自动快照（每轮防抖写入）",
    "snap": "手动快照",
    "pre-restore": "恢复前自动留档（可回退本次恢复）",
}


class RestoreRequest(BaseModel):
    """恢复请求体：confirm=true 才执行（敏感操作显式确认）。"""

    confirm: bool = False


def _service_for(agent_id: str):
    """解析该 agent 的 CheckpointService：优先复用运行实例上缓存的那个
    （与 _auto_checkpoint 同一实例、同一防抖状态），实例不在运行（仅配置态）
    时按同一落点现建——落点是数据根的确定性函数，两法指向同一 git 仓。"""
    from neurova.core.agent_workspaces import agent_exists

    if not agent_exists(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
    from neurova.api.endpoints import get_agent_instance

    agent = get_agent_instance(agent_id)
    if agent is not None:
        cached = getattr(agent, "_checkpoint_service", None)
        if cached is not None:
            return cached
    from neurova.checkpoints.service import CheckpointService

    return CheckpointService(agent_id=agent_id)


def _session_key_of(ref: str) -> str:
    """从 ref 规范 refs/{kind}/{session_key}/{ts} 取 session_key（与
    CheckpointService.restore_snapshot 同一解析口径）。"""
    parts = ref.split("/")
    if len(parts) < 4 or parts[0] != "refs":
        raise ValueError(f"非法检查点 ref: {ref!r}")
    return parts[2]


def _current_session_owner(agent_id: str, session_key: str) -> str:
    """恢复前读出会话属主——恢复不得改写可见性归属（删了重建时随行）。

    P0-08 fail-closed：属主读取失败直接抛错中止恢复（在 delete 之前），
    不再回落「按共享会话处理」的旧语义。
    """
    from neurova.session_manager import get_session_manager

    try:
        record = get_session_manager().get_session(agent_id, session_key)
    except Exception as exc:
        raise RuntimeError(f"恢复前读取会话属主失败（agent={agent_id} session={session_key}）: {exc}") from exc
    return str(getattr(record, "user_id", "") or "")


def _sync_agent_memory_mirror(agent_id: str, messages: List[Dict[str, Any]]) -> None:
    """把恢复后的历史同步进运行中 agent 的内存镜像。

    会话上下文的权威读口在 session_manager（盘上），但运行中的 agent 还持有
    conversation_history / _conversation_context 两份镜像；不同步的话，恢复
    后的下一轮 update_history 会把内存里那份"未来"历史原样续写回去。
    """
    from neurova.api.endpoints import get_agent_instance

    agent = get_agent_instance(agent_id)
    if agent is None:
        return
    mirror: List[Dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "")
        if not role:
            continue
        item: Dict[str, Any] = {"role": role, "content": str(msg.get("content") or "")}
        if msg.get("metadata"):
            item["metadata"] = msg["metadata"]
        mirror.append(item)
    try:
        ctx = getattr(agent, "_conversation_context", None)
        if ctx is not None:
            ctx.clear()
            ctx.extend(mirror)
        agent.conversation_history = mirror
    except Exception as exc:  # noqa: BLE001 - 镜像同步失败不阻断恢复本身
        logger.warning("恢复后同步 agent 内存历史失败（盘上已恢复）: %s", exc)


def _apply_restore(agent_id: str, session_key: str):
    """构造 restore_with_rollback 的 apply_fn：把快照会话内容写回盘上。"""

    def apply(payload: Dict[str, Any]) -> None:
        from neurova.session_manager import get_session_manager

        sm = get_session_manager()
        data = json.loads(payload.get("session_json") or "{}")
        messages = data.get("messages") or []

        owner = _current_session_owner(agent_id, session_key)
        if not owner:
            # P0-08：空属主（含无历史会话的新建语义）归主管理员
            # （2026-11-18 用户拍板，废止旧「空即共享」）。
            from neurova.post_chat_pipeline import _adminOwnerId

            owner = str(_adminOwnerId() or "").strip()
        if not owner:
            # 解析不出主管理员 → fail-closed。恢复会删掉原会话再重建，
            # 绝不允许在归属未知时动手。
            raise RuntimeError(
                f"会话 {session_key} 的属主无法解析（空属主且无主管理员），已中止恢复"
            )
        # 先清后写：会话文件按日期分片，get_history 聚合全部日期——
        # 只追加不清理会把"未来"轮次留在恢复点之后。
        sm.delete_session(agent_id, session_key)
        for msg in messages:
            role = str(msg.get("role") or "")
            if not role:
                continue
            ok = sm.save_message(
                agent_id=agent_id,
                session_id=session_key,
                role=role,
                content=str(msg.get("content") or ""),
                metadata=msg.get("metadata"),
                user_id=owner,
            )
            if not ok:
                raise RuntimeError(
                    f"会话消息写回失败（session={session_key} role={role}）"
                )
        _sync_agent_memory_mirror(agent_id, messages)

    return apply


def _audit_restore(
    agent_id: str, ref: str, session_key: str, user_id: str, request: Request
) -> None:
    """恢复落审计（S8 同源 audit_logger；fail-open：写失败只告警不阻断）。"""
    try:
        from neurova.security.audit_logger import (
            AuditEventType,
            AuditLogEntry,
            AuditSeverity,
            get_audit_logger,
        )

        client_host = request.client.host if request and request.client else ""
        get_audit_logger().log(
            AuditLogEntry(
                event_type=AuditEventType.SECURITY_EVENT,
                severity=AuditSeverity.HIGH,
                user_id=user_id,
                action="checkpoint_restore",
                details={
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "ref": ref,
                },
                ip_address=client_host,
                resource_type="checkpoint",
                resource_id=ref,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 审计失败不阻断恢复
        logger.warning("检查点恢复审计写入失败（不阻断恢复）: %s", exc)


@router.get("/{agent_id}/checkpoints")
async def list_checkpoints(
    request: Request,
    agent_id: str = FastAPIPath(...),
    session_id: Optional[str] = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出该 agent 的检查点快照（按 auto/snap/pre-restore 分组，时间降序）。

    session_id 可选：给定时只列该会话；缺省列全部会话。
    """
    requireAgentOwner(agent_id, current_user, action="查看检查点")
    service = _service_for(agent_id)
    snaps = service.list_snapshots(session_key=session_id)

    grouped: Dict[str, List[Dict[str, Any]]] = {"auto": [], "snap": [], "pre_restore": []}
    for snap in snaps:
        group = _GROUP_KEYS.get(snap["kind"], snap["kind"])
        ts_tail = snap["ref"].rsplit("/", 1)[-1]
        grouped.setdefault(group, []).append(
            {
                "ref": snap["ref"],
                "kind": snap["kind"],
                "session_key": snap["session_key"],
                "timestamp": snap["timestamp"],
                "time": datetime.fromtimestamp(snap["timestamp"]).isoformat(),
                "ts": ts_tail,
                "label": _KIND_LABELS.get(snap["kind"], snap["kind"]),
            }
        )
    return {
        "agent_id": agent_id,
        "session_id": session_id,
        "total": len(snaps),
        **grouped,
    }


@router.post("/{agent_id}/checkpoints/{ref:path}/restore")
async def restore_checkpoint(
    request: Request,
    agent_id: str = FastAPIPath(...),
    ref: str = FastAPIPath(...),
    body: Optional[RestoreRequest] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """恢复到指定检查点（事务化：apply 失败自动回滚到恢复前状态）。

    敏感操作双闸：归属门（requireAgentOwner）+ 显式确认（confirm=true）；
    成功落 SECURITY_EVENT 审计。
    """
    requireAgentOwner(agent_id, current_user, action="恢复检查点")
    body = body or RestoreRequest()
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail='恢复是敏感操作：请求体须携带 {"confirm": true} 显式确认',
        )

    try:
        session_key = _session_key_of(ref)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    service = _service_for(agent_id)
    try:
        payload = service.restore_with_rollback(ref, apply_fn=_apply_restore(agent_id, session_key))
    except ValueError as exc:
        # 检查点不存在 / ref 非法 → 404（deny 与不存在同构，防枚举）
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    _audit_restore(
        agent_id, ref, session_key, str(current_user.get("user_id") or ""), request
    )

    restored_messages = []
    try:
        restored_messages = json.loads(payload.get("session_json") or "{}").get("messages") or []
    except Exception:  # noqa: BLE001 - 回执统计失败不影响恢复结果
        pass
    return {
        "restored": True,
        "agent_id": agent_id,
        "session_key": session_key,
        "ref": ref,
        "pre_restore_ref": payload.get("pre_restore_ref"),
        "messages_restored": len(restored_messages),
    }
