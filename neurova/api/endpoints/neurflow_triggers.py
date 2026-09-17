"""Trigger ingress, CRUD and delivery routes (two ordered registration segments)."""
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from neurova.api.auth import get_current_user
from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger

router = APIRouter()
deliveries_router = APIRouter()

# ==================== P1 Step 4b — Webhook 入站触发（薄壳） ====================


from neurova.collaboration.neurflow import webhook_ingress  # noqa: E402
from neurova.core.trigger_rate_limiter import TriggerRateLimiter  # noqa: E402

# 每 trigger_id 缓存的限流桶（跨请求共享；rate_limiter_for 消费）
_WEBHOOK_RATE_LIMITERS: Dict[str, TriggerRateLimiter] = {}


def _webhook_ingress_deps() -> Dict[str, Any]:
    """装配 webhook_ingress 默认 deps（trigger/workflow 加载 + 解密 + 执行）。

    安全语义：仅 PUBLISHED 状态的工作流可被 webhook 派发。
    """
    from neurova.api.endpoints import neurflow_api as api

    from neurova.core.trigger_rate_limiter import TriggerRateLimiter
    from neurova.llm.providers.secret_store import decrypt_api_key
    from neurova.collaboration.neurflow.models import WorkflowStatus

    def load_trigger(tid: str):
        return api._get_storage().get_trigger(tid)

    def load_published_workflow(ref: str):
        storage = api._get_storage()
        wf = storage.get_workflow(ref)
        if wf is not None and wf.status == WorkflowStatus.PUBLISHED:
            return wf
        return None

    async def run_workflow(workflow, inputs, user_id=None):
        # P0-1：匿名 HMAC 入口按 workflow 属主执行/记账（trigger→workflow 反查）
        effective = user_id or getattr(workflow, "user_id", None) or None
        return await api.get_workflow_executor().execute(
            workflow=workflow, inputs=inputs, user_id=effective
        )

    def rate_limiter_for(trigger):
        """按 trigger_id 缓存 limiter（跨请求共享桶，限流才生效）。"""
        tid = getattr(trigger, "id", "")
        limiter = api._WEBHOOK_RATE_LIMITERS.get(tid)
        if limiter is None:
            limiter = TriggerRateLimiter(getattr(trigger, "rate_limit_per_minute", None))
            api._WEBHOOK_RATE_LIMITERS[tid] = limiter
        return limiter

    return {
        "load_trigger": load_trigger,
        "load_published_workflow": load_published_workflow,
        "decrypt_secret": decrypt_api_key,
        "run_workflow": run_workflow,
        "rate_limiter_for": rate_limiter_for,
    }


# P0-7/N4：入站 body 上限（1MB）——限流在验签后，但超大 body 会先于一切
# 消耗内存与带宽，必须在读 body 前按 Content-Length 硬拒
_WEBHOOK_MAX_BODY_BYTES = 1024 * 1024


@router.post("/triggers/webhook/{trigger_id}/receive")
async def receive_webhook_trigger(trigger_id: str, request: Request):
    """外部系统入站触发工作流（HMAC 验签 + 重放防护 + 限流 + 派发；逻辑在 webhook_ingress）。

    投递审计：无论成败均落 webhook_deliveries（P1 Step 7 表）。
    """
    from neurova.api.endpoints import neurflow_api as api

    declared = request.headers.get("content-length")
    try:
        if declared and int(declared) > api._WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="PAYLOAD_TOO_LARGE")
    except ValueError:
        pass

    payload = await request.body()
    if len(payload) > api._WEBHOOK_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="PAYLOAD_TOO_LARGE")

    header_sig = request.headers.get("X-Hub-Signature-256")
    header_ts = request.headers.get("X-Neurova-Timestamp")
    try:
        result = await api.webhook_ingress.handle_webhook_ingress(
            trigger_id, payload, header_sig, timestamp_header=header_ts
        )
    except api.webhook_ingress.IngressRejected as e:
        sig_valid = e.reason not in ("INVALID_SIGNATURE", "TRIGGER_NOT_FOUND")
        try:
            api._get_storage().save_delivery(
                trigger_id=trigger_id,
                signature_valid=sig_valid,
                execution_id=None,
                status_code=e.status_code,
            )
        except Exception:
            api.logger.warning("delivery record failed (rejected path): %s", trigger_id)
        raise HTTPException(status_code=e.status_code, detail=e.reason)

    try:
        api._get_storage().save_delivery(
            trigger_id=trigger_id,
            signature_valid=True,
            execution_id=(result.get("data") or {}).get("execution_id"),
            status_code=200,
        )
    except Exception:
        api.logger.warning("delivery record failed (success path): %s", trigger_id)
    return result


# ==================== P1 Step 6 — 触发器 CRUD API ====================


class TriggerCreateRequest(BaseModel):
    """创建触发器请求体"""

    type: str  # "webhook" | "cron" | "manual"
    config: Dict[str, Any] = {}
    rate_limit_per_minute: Optional[int] = None


@router.get("/workflows/{workflow_id}/triggers")
async def list_workflow_triggers(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出某工作流的全部触发器（secret 字段不回显）。"""
    from neurova.api.endpoints import neurflow_api as api

    storage = api._get_storage()
    items = storage.list_triggers_by_workflow(workflow_id)
    return {
        "code": 0,
        "data": [
            {
                "id": t.id,
                "workflow_id": t.workflow_id,
                "type": t.type.value,
                "enabled": t.enabled,
                "config": t.config,
                "rate_limit_per_minute": t.rate_limit_per_minute,
                "created_at": t.created_at,
            }
            for t in items
        ],
    }


@router.post("/workflows/{workflow_id}/triggers")
async def create_workflow_trigger(
    workflow_id: str,
    body: TriggerCreateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """创建触发器。

    webhook：自动生成 secret —— 明文仅本次响应返回一次，
    库中存 AES-GCM 密文（验签用）+ sha256 hash（审计用）。
    cron：校验 cron 表达式可解析。
    """
    from neurova.api.endpoints import neurflow_api as api

    import secrets as _secrets

    from neurova.llm.providers.secret_store import encrypt_api_key

    storage = api._get_storage()
    if not api._owned_workflow_or_404(storage, workflow_id, current_user):
        raise HTTPException(status_code=404, detail="工作流不存在")

    try:
        trigger_type = TriggerType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="type 必须为 webhook/cron/manual")

    trigger_id = f"trg_{uuid.uuid4().hex[:12]}"
    now = time.time()
    secret_plain = None
    secret_encrypted = None
    secret_hash = None

    if trigger_type == TriggerType.WEBHOOK:
        secret_plain = _secrets.token_urlsafe(32)
        secret_encrypted = encrypt_api_key(secret_plain)
        secret_hash = api.NeurflowStorage.hash_trigger_secret(secret_plain)
    elif trigger_type == TriggerType.CRON:
        cron_expr = (body.config or {}).get("cron")
        if not cron_expr:
            raise HTTPException(status_code=400, detail="cron 触发器需要 config.cron 表达式")
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(cron_expr)
        except Exception:
            raise HTTPException(status_code=400, detail="cron 表达式无法解析")

    trigger = WorkflowTrigger(
        id=trigger_id,
        workflow_id=workflow_id,
        type=trigger_type,
        enabled=True,
        config=body.config or {},
        secret_hash=secret_hash,
        secret_encrypted=secret_encrypted,
        rate_limit_per_minute=body.rate_limit_per_minute,
        created_at=now,
        updated_at=now,
    )
    storage.save_trigger(trigger)

    # cron 触发器尝试即时注册（scheduler 未配置则跳过，启动恢复时补齐）
    if trigger_type == TriggerType.CRON:
        try:
            from neurova.collaboration.neurflow.triggers import get_trigger_manager

            await get_trigger_manager().register_cron(trigger)
        except Exception as e:
            api.logger.warning("cron trigger register deferred: %s", e)

    resp: Dict[str, Any] = {
        "code": 0,
        "data": {
            "trigger": {
                "id": trigger.id,
                "workflow_id": trigger.workflow_id,
                "type": trigger.type.value,
                "enabled": trigger.enabled,
                "config": trigger.config,
                "rate_limit_per_minute": trigger.rate_limit_per_minute,
                "secret_encrypted": None,
                "created_at": trigger.created_at,
            }
        },
    }
    if secret_plain is not None:
        resp["data"]["secret"] = secret_plain
    return resp


@router.delete("/triggers/{trigger_id}")
async def delete_workflow_trigger(
    trigger_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除触发器；同步移除 cron job。"""
    from neurova.api.endpoints import neurflow_api as api

    storage = api._get_storage()
    if not storage.get_trigger(trigger_id):
        raise HTTPException(status_code=404, detail="触发器不存在")
    storage.delete_trigger(trigger_id)
    try:
        from neurova.collaboration.neurflow.triggers import get_trigger_manager

        await get_trigger_manager().unregister(trigger_id)
    except Exception:
        pass
    return {"code": 0, "message": "deleted"}


@router.post("/triggers/{trigger_id}/fire")
async def fire_trigger(
    trigger_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """手动触发（manual/测试用）：按触发器绑定的 workflow 直接派发。"""
    from neurova.api.endpoints import neurflow_api as api

    storage = api._get_storage()
    trigger = storage.get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="触发器不存在")

    from neurova.collaboration.neurflow.models import WorkflowStatus

    wf = storage.get_workflow(trigger.workflow_id)
    if wf is None or wf.status != WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=404, detail="工作流未发布")

    async def _run(workflow, inputs):
        return await api.get_workflow_executor().execute(workflow=workflow, inputs=inputs)

    from neurova.agent.scheduler import WorkflowTaskExecutor

    executor = WorkflowTaskExecutor(
        workflow_loader=lambda ref: wf if ref == trigger.workflow_id else None,
        workflow_runner_callable=_run,
    )
    result = await executor.dispatch_neurflow(trigger.workflow_id, body or {})
    return {"code": 0, "data": result}


# ==================== P1 Step 7 — 投递记录查询 ====================


@router.get("/triggers/{trigger_id}/deliveries")
async def list_trigger_deliveries(
    trigger_id: str,
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """查询 webhook 入站投递记录（调试面板用）。"""
    from neurova.api.endpoints import neurflow_api as api

    storage = api._get_storage()
    return {"code": 0, "data": storage.list_deliveries(trigger_id, limit=limit)}


# ══════════════════════════════════════════════════════════════
# P2 trigger 统一契约 — 投递重试管理 API
# ══════════════════════════════════════════════════════════════


async def handle_webhook_ingress_simple(trigger_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """按 trigger_id 重投（重试链路的重放壳）。

    直接调 handle_webhook_ingress（完整验签/限流/派发语义）；宽松模式
    trigger 空负载即可重放；严格模式 trigger 无原始签名头——重试链路
    以 INGRESS 侧结果为准（4xx 视为不可重投失败，由账目标 dead/pending）。
    """
    import json as _json

    from neurova.collaboration.neurflow import webhook_ingress as _ingress

    try:
        outcome = await _ingress.handle_webhook_ingress(
            trigger_id, _json.dumps(payload or {}).encode("utf-8"),
            signature_header=None, timestamp_header=None,
        )
        return {"success": True, "execution_id": (outcome or {}).get("execution_id"),
                "raw": outcome}
    except _ingress.IngressRejected as e:
        return {"success": False, "error": f"{e.status_code} {e.reason}"}


def _get_retry_service() -> "Any":
    from neurova.api.endpoints import neurflow_api as api

    from neurova.collaboration.neurflow.trigger_retry import TriggerRetryService

    return TriggerRetryService(api._get_storage())


@deliveries_router.get("/trigger/deliveries/failed")
async def list_failed_deliveries(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """失败投递队列（重试管理页数据源）。"""
    from neurova.api.endpoints import neurflow_api as api

    svc = api._get_retry_service()
    return {"code": 0, "message": "ok", "data": {"items": svc.list_failed(limit=limit)}}


@deliveries_router.post("/trigger/deliveries/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """手动重试单条失败投递（重新走 webhook 入站验签+执行链路）。"""
    from neurova.api.endpoints import neurflow_api as api

    async def _redeliver(trigger_id: str, attempt: int) -> Dict[str, Any]:
        from neurova.api.endpoints import neurflow_api as _self

        deps = _self._webhook_ingress_deps()
        try:
            trigger = deps["load_trigger"](trigger_id)
            if trigger is None:
                return {"ok": False, "error": "trigger 不存在"}
            # 重新投递：空 payload 重放（签名按 trigger secret 重新计算语义
            # 由 handle_webhook_ingress 的宽松/严格模式处理）
            outcome = await _self.handle_webhook_ingress_simple(trigger_id, {})
            return {"ok": bool(outcome.get("success") or outcome.get("execution_id")),
                    "execution_id": outcome.get("execution_id")}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    svc = api._get_retry_service()
    outcome = await svc.retry_delivery(delivery_id, redeliver=_redeliver)
    return {"code": 0, "message": "ok", "data": outcome}


@deliveries_router.post("/trigger/deliveries/retry-due")
async def retry_due_deliveries(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """到期批量重试（后台调度亦可调用此入口）。"""
    from neurova.api.endpoints import neurflow_api as api

    async def _redeliver(trigger_id: str, attempt: int) -> Dict[str, Any]:
        try:
            from neurova.api.endpoints import neurflow_api as _self

            outcome = await _self.handle_webhook_ingress_simple(trigger_id, {})
            return {"ok": bool(outcome.get("success") or outcome.get("execution_id")),
                    "execution_id": outcome.get("execution_id")}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    svc = api._get_retry_service()
    processed = await svc.retry_due(redeliver=_redeliver)
    return {"code": 0, "message": "ok", "data": {"processed": processed, "count": len(processed)}}
