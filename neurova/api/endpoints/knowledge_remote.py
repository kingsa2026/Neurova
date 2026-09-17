"""远程知识库托管端点（R-7(A) configs/collections + 摄取队列观测 ingress-tasks）。

2026-09-16 自 knowledge.py 拆出；路径与响应契约不变。
本模块路由全部为字面前缀（/configs /collections /ingress-tasks），
无 GET /{knowledge_id} 遮蔽风险（见 test_knowledge_route_order.py）。

依赖方向（架构约束，2026-09-16 拆分后冻结；全图见 knowledge.py 头部）：
    本模块 ──▶ knowledge_common（repository 解析等）
              ──▶ neurova.knowledge.storage（_get_kb_storage，函数内懒导入）
    禁止：本模块 import 兄弟叶子（core/sharing/ingestion），也禁止 import
    聚合器 knowledge.py（成环）；共享需求下沉 knowledge_common。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from neurova.api.auth import get_current_user_or_service
from neurova.api.endpoints.knowledge_common import get_repository


def _get_kb_storage():
    """用户级远程知识库配置存储（configs/collections）。"""
    from neurova.knowledge.storage import get_knowledge_storage

    return get_knowledge_storage()


router = APIRouter()


@router.get("/configs")
async def list_kb_configs(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """列出当前用户全部远程知识库配置（不回显密钥）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    return {
        "code": 0,
        "data": {
            "configs": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "source_type": c.get("source_type"),
                    "is_default": c.get("is_default"),
                    "is_active": c.get("is_active"),
                    "settings": c.get("settings", {}),
                    "has_api_key": bool(c.get("api_key_hash")),
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                }
                for c in storage.get_configs_by_user(user_id)
            ]
        },
    }


@router.post("/configs")
async def create_kb_config(request: Request, body: dict, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """创建远程知识库配置（API Key 加密存储，不回显）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cid = storage.create_config(
        user_id=user_id,
        name=str(body.get("name", "") or ""),
        source_type=str(body.get("source_type", "") or "custom"),
        is_default=bool(body.get("is_default", False)),
        is_active=bool(body.get("is_active", False)),
        api_key=str(body.get("api_key", "") or "") or None,
        settings=body.get("settings"),
    )
    return {"code": 0, "data": {"id": cid}}


@router.get("/configs/{config_id}")
async def get_kb_config(request: Request, config_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """获取单个配置（属主；回显元数据不含密钥）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    return {
        "code": 0,
        "data": {
            "id": cfg.get("id"),
            "name": cfg.get("name"),
            "source_type": cfg.get("source_type"),
            "settings": cfg.get("settings", {}),
            "has_api_key": bool(cfg.get("api_key_hash")),
            "is_default": cfg.get("is_default"),
            "is_active": cfg.get("is_active"),
        },
    }


@router.put("/configs/{config_id}")
async def update_kb_config(request: Request, config_id: str = Path(...), body: dict = None, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """更新配置（api_key 传新值则重加密）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    fields: Dict[str, Any] = {}
    for k in ("name", "source_type", "settings"):
        if body and k in body:
            fields[k] = body[k]
    if body is not None and body.get("api_key") is not None:
        fields["api_key"] = body["api_key"]
    storage.update_config(config_id, **fields)
    return {"code": 0, "message": "updated"}


@router.delete("/configs/{config_id}")
async def delete_kb_config(request: Request, config_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """删除配置（属主）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    storage.delete_config(config_id)
    return {"code": 0, "message": "deleted"}


@router.post("/configs/{config_id}/sync")
async def sync_kb_config(
    request: Request,
    config_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """触发一次远程数据源增量同步落库（P1#9，当前支持飞书知识空间）。

    属主校验 → 装配适配器 → run_feishu_sync（游标持久化在 settings._sync）。
 并发互斥：同配置已有同步在跑 → 409。
    """
    from neurova.knowledge.datasource_sync import SyncBusyError, run_feishu_sync

    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    if str(cfg.get("source_type", "")) != "feishu":
        raise HTTPException(status_code=400, detail="当前仅飞书知识空间支持同步落库")
    settings = dict(cfg.get("settings") or {})
    api_key = storage.decrypt_api_key(config_id)
    if api_key:
        # 飞书 app_secret 经顶层 api_key Fernet 加密存储（见创建表单主凭据通道）
        # ——FeishuKBAdapter 契约读 app_secret，映射回去；api_key 一并保留兼容。
        settings.setdefault("app_secret", api_key)
        settings["api_key"] = api_key
    try:
        from neurova.knowledge.adapters import FeishuKBAdapter

        adapter = FeishuKBAdapter(settings)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="适配器装配失败: %s" % e)
    repo = get_repository()
    try:
        stats = await run_feishu_sync(
            adapter, repo, storage, config_id=config_id, user_id=user_id,
            agent_id=str(request.query_params.get("agent_id") or "default"),
        )
    except SyncBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "success", "data": stats}


@router.get("/collections")
async def list_kb_collections(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """列出当前用户的集合映射。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    return {"code": 0, "data": {"collections": storage.get_user_collections(user_id)}}


@router.post("/collections")
async def create_kb_collection(request: Request, body: dict, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """创建集合映射（config_id + collection_name + vector_store）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    mid = storage.create_collection_mapping(
        user_id,
        str(body.get("config_id", "") or ""),
        str(body.get("collection_name", "") or ""),
        vector_store=str(body.get("vector_store", "qdrant") or "qdrant"),
    )
    return {"code": 0, "data": {"id": mid}}


@router.delete("/collections/{mapping_id}")
async def delete_kb_collection(request: Request, mapping_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """删除集合映射（属主）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    items = storage.get_user_collections(user_id)
    if not any(i.get("id") == mapping_id for i in items):
        raise HTTPException(status_code=404, detail=f"Collection '{mapping_id}' not found")
    storage.delete_collection_mapping(mapping_id)
    return {"code": 0, "message": "deleted"}


# ── 知识摄取队列观测（P1-#9） ─────────────────────────────────────


@router.get("/ingress-tasks")
async def list_ingress_tasks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """摄取任务列表 + 计数（本人任务；admin 全量）。"""
    from neurova.knowledge.ingest_queue import get_ingress_queue

    queue = get_ingress_queue()
    uid = str(current_user.get("user_id") or "")
    is_admin = str(current_user.get("role") or "") == "admin"
    tasks = queue.list_recent(limit=limit)
    if not is_admin:
        tasks = [t for t in tasks if t.get("user_id") == uid]
    return {"code": 0, "data": {"tasks": tasks, "stats": queue.stats()}}


@router.get("/ingress-tasks/{task_id}")
async def get_ingress_task(
    task_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """单任务状态（pending/processing/done/dead/cancelled；done 附 item_ids，
    并附 P1#12 spans 阶段时间线）。"""
    from neurova.knowledge.ingest_queue import get_ingress_queue

    queue = get_ingress_queue()
    row = queue.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    uid = str(current_user.get("user_id") or "")
    if row.get("user_id") != uid and str(current_user.get("role") or "") != "admin":
        # 他人任务对普通用户按不存在处理（不泄露存在性）
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    row = dict(row)
    try:
        import json as _json

        row["item_ids"] = _json.loads(row.get("result_ids") or "[]")
    except Exception:  # noqa: BLE001
        row["item_ids"] = []
    row["spans"] = queue.get_spans(task_id)
    row.pop("storage_path", None)  # 服务端绝对路径不外露
    return {"code": 0, "data": row}


@router.post("/ingress-tasks/{task_id}/cancel")
async def cancel_ingress_task(
    task_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """取消待处理/处理中的摄取任务（P1#12 stop-parse lite）。

    属主/admin；已 done/dead/cancelled → 409（不谎报取消）。在飞 worker 完成
    时被队列 ack/nack 守卫拦截，不会把 cancelled 复活为 done/dead。
    """
    from neurova.knowledge.ingest_queue import get_ingress_queue

    queue = get_ingress_queue()
    row = queue.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    uid = str(current_user.get("user_id") or "")
    if row.get("user_id") != uid and str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    ok = queue.cancel_task(task_id, by=uid)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="任务已完成或已终结，无法取消（当前状态: %s）" % row.get("status"),
        )
    return {"code": 0, "message": "cancelled", "data": {"task_id": task_id}}
