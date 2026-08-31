"""
Neurflow API — 工作流管理端点
提供工作流 CRUD、执行、节点注册、DAG 验证等 RESTful 接口
"""

from neurova.core.logger import get_logger
import json
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.endpoints import get_agent_instance
from neurova.collaboration.neurflow.dag import get_dag_validator
from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
from neurova.collaboration.neurflow.models import (
    TriggerType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    WorkflowTrigger,
    WorkflowVariable,
)
from neurova.collaboration.neurflow.node_registry import get_node_registry
from neurova.collaboration.neurflow.storage import NeurflowStorage

logger = get_logger(__name__)

router = APIRouter()


def _port_to_dict(p) -> Dict[str, Any]:
    """
    将端口（input/output）序列化为字典。

    兼容两种存储格式：NodePort 对象或 dict。
    """
    if isinstance(p, dict):
        return {"id": p.get("id", ""), "label": p.get("label", "")}
    return {"id": getattr(p, "id", ""), "label": getattr(p, "label", "")}


def _sub_block_to_dict(b) -> Dict[str, Any]:
    """
    将 sub_block 序列化为前端画布可用的完整字典。

    兼容两种存储格式：
    - SubBlockConfig 对象（属性访问）
    - dict（注册表实际存储格式，键名可能有 id/name、title/label、default_value/default 之分）

    返回包含 default_value/options/min/max/placeholder 等完整字段，
    供前端画布节点库渲染 select/slider/textarea 等配置表单。
    """
    if isinstance(b, dict):
        return {
            "id": b.get("id") or b.get("name") or "",
            "title": b.get("title") or b.get("label") or "",
            "type": b.get("type", "input"),
            "required": bool(b.get("required", False)),
            "default_value": b.get("default_value", b.get("default")),
            "options": b.get("options") or [],
            "placeholder": b.get("placeholder", ""),
            "description": b.get("description", ""),
            "min": b.get("min"),
            "max": b.get("max"),
            "language": b.get("language"),
            # 条件可见（联动下拉）：{field, operator, value}，前端按当前 config 过滤字段显隐
            "condition": b.get("condition"),
        }
    # SubBlockConfig / 其他对象
    return {
        "id": getattr(b, "id", ""),
        "title": getattr(b, "title", ""),
        "type": getattr(b, "type", "input"),
        "required": bool(getattr(b, "required", False)),
        "default_value": getattr(b, "default_value", None),
        "options": getattr(b, "options", None) or [],
        "placeholder": getattr(b, "placeholder", ""),
        "description": getattr(b, "description", ""),
        "min": getattr(b, "min", None),
        "max": getattr(b, "max", None),
        "language": getattr(b, "language", None),
        "condition": getattr(b, "condition", None),
    }


def _get_storage() -> NeurflowStorage:
    """获取存储实例（延迟初始化）"""
    if not hasattr(_get_storage, "_instance"):
        _get_storage._instance = NeurflowStorage()
    return _get_storage._instance


# ==================== 店铺连接（/stores） ====================

_STORE_FIELD_KEYS = (
    "store_name",
    "seller_id",
    "marketplace_id",
    "region",
    "extra",
    "status",
    "token_expires_at",
    "credentials",
)


def _get_store_manager():
    from neurova.collaboration.neurflow.store_connections import get_store_connection_manager

    return get_store_connection_manager()


@router.get("/stores")
async def list_stores(
    platform: Optional[str] = Query(None, description="按平台过滤"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """店铺列表（密钥脱敏；按归属用户隔离）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    stores = manager.list_stores(platform or "", user_id=user_id)
    return {"stores": [manager.mask(s) for s in stores], "total": len(stores)}


@router.post("/stores")
async def create_store(
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """连接店铺：注册表 + 凭据入库（Tier 1 手工录入）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    platform = str(data.get("platform") or "").strip()
    store_name = str(data.get("store_name") or "").strip()
    if not platform or not store_name:
        raise HTTPException(status_code=400, detail="platform 与 store_name 必填")
    if platform not in ("amazon", "taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"):
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    fields = {k: v for k, v in data.items() if k in _STORE_FIELD_KEYS and k != "store_name"}
    try:
        conn = manager.create_store(
            platform, store_name, credentials=fields.pop("credentials", None) or None, user_id=user_id, **fields
        )
        return {"store": manager.mask(conn), "message": "店铺连接成功"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"创建店铺失败: {str(exc)}")


@router.get("/stores/{store_id}")
async def get_store(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """店铺详情（脱敏；仅限归属用户）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    store = manager.get_store(store_id, user_id=user_id)
    if store is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    return {"store": manager.mask(store)}


@router.put("/stores/{store_id}")
async def update_store(
    store_id: str,
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """更新店铺（名称/站点参数/凭据轮换；仅限归属用户）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    fields = {k: v for k, v in data.items() if k in _STORE_FIELD_KEYS}
    try:
        conn = manager.update_store(store_id, credentials=fields.pop("credentials", None) or None, user_id=user_id, **fields)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"更新店铺失败: {str(exc)}")
    if conn is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    return {"store": manager.mask(conn), "message": "店铺已更新"}


@router.delete("/stores/{store_id}")
async def delete_store(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """删除店铺（含 SecretStore 密钥清理；仅限归属用户）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if not manager.delete_store(store_id, user_id=user_id):
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    return {"message": "店铺已删除"}


@router.post("/stores/{store_id}/test")
async def test_store_connection(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """连接测试（只读探针；仅限归属用户）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if manager.get_store(store_id, user_id=user_id) is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    result = await manager.test_connection(store_id, user_id=user_id)
    return {"result": result}


@router.post("/stores/{store_id}/refresh")
async def refresh_store_token(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """强制刷新令牌（仅限归属用户）"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if manager.get_store(store_id, user_id=user_id) is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    result = await manager.refresh_token(store_id, user_id=user_id)
    return {"result": result}


# ==================== Tier 2 OAuth（一键授权跳转） ====================
# 依据 docs/neurflow-store-connection-design.md §2（2026-08-29 复核）：
# - 1688：auth.1688.com/oauth/authorize（已核实，路径经网关探测）
# - 小红书：ark.xiaohongshu.com/ark/authorization（已核实）
# - 淘宝/闲鱼：TOP oauth（oauth.taobao.com；闲鱼复用 TOP 生态）
# - 京东/拼多多/抖店/TikTok：各平台 OAuth 授权跳转（URL 形态按公开文档，实施以平台后台核对为准）
# 亚马逊为卖家中心自授权（无跳转），不支持 Tier 2。

_OAUTH_SUPPORTED = ("taobao", "xianyu", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu")
_OAUTH_STATE_TTL_SECONDS = 30 * 60


def _oauth_callback_uri(request: Request) -> str:
    return str(request.base_url) + "api/v1/neurflow/stores/oauth/callback"


def _oauth_authorize_url(platform: str, app_key: str, redirect_uri: str, state: str) -> str:
    from urllib.parse import quote

    enc_uri = quote(redirect_uri, safe="")
    if platform in ("taobao", "xianyu"):
        return f"https://oauth.taobao.com/authorize?response_type=code&client_id={app_key}&redirect_uri={enc_uri}&state={state}"
    if platform == "jd":
        return f"https://open-oauth.jd.com/oauth2/authorize?app_key={app_key}&redirect_uri={enc_uri}&state={state}"
    if platform == "pdd":
        return f"https://open-api.pinduoduo.com/oauth/authorize?client_id={app_key}&redirect_uri={enc_uri}&state={state}"
    if platform == "douyin-ecom":
        return f"https://op.jinritemai.com/authorize?service_id={app_key}&redirect_uri={enc_uri}&state={state}"
    if platform == "tiktok":
        return f"https://services.tiktokshop.com/open/authorize?app_key={app_key}&redirect_uri={enc_uri}&state={state}"
    if platform == "ali1688":
        return f"https://auth.1688.com/oauth/authorize?client_id={app_key}&site=1688&redirect_uri={enc_uri}&state={state}"
    if platform == "xiaohongshu":
        return f"https://ark.xiaohongshu.com/ark/authorization?appId={app_key}&redirectUri={enc_uri}&state={state}"
    return ""


async def _oauth_exchange_token(platform: str, app_key: str, app_secret: str, code: str, redirect_uri: str) -> Dict[str, Any]:
    """按平台换 token：返回 {access_token, refresh_token?, expires_in?}"""
    from neurova.collaboration.neurflow.external_api import _http_post

    if platform == "ali1688":
        from neurova.collaboration.neurflow.external_api import get_alibaba1688_client

        token = await get_alibaba1688_client().fetch_token(
            app_key=app_key, app_secret=app_secret, code=code, redirect_uri=redirect_uri
        )
        return {"access_token": token}
    if platform == "xiaohongshu":
        from neurova.collaboration.neurflow.external_api import get_xiaohongshu_client

        token = await get_xiaohongshu_client().get_access_token(app_key=app_key, app_secret=app_secret, code=code)
        return {"access_token": token}

    urls = {
        "taobao": "https://oauth.taobao.com/token",
        "xianyu": "https://oauth.taobao.com/token",
        "jd": "https://open-oauth.jd.com/oauth2/token",
        "pdd": "https://open-api.pinduoduo.com/oauth/token",
        "douyin-ecom": "https://openapi-fxg.jinritemai.com/oauth2/access_token",
        "tiktok": "https://open-api.tiktokglobalshop.com/api/v2/token/get",
    }
    params = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    if platform == "tiktok":
        params = {"grant_type": "authorized_code", "auth_code": code}
    if platform in ("taobao", "xianyu", "pdd"):
        params.update({"client_id": app_key, "client_secret": app_secret})
    elif platform == "jd":
        params.update({"app_key": app_key, "app_secret": app_secret})
    elif platform in ("douyin-ecom", "tiktok"):
        params.update({"app_key": app_key, "app_secret": app_secret})
    data = await _http_post(urls[platform], data=params)
    payload = data if isinstance(data, dict) else {}
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    token = payload.get("access_token") or inner.get("access_token") or inner.get("accessToken")
    if not token:
        raise HTTPException(status_code=400, detail=f"令牌交换失败: {data}")
    out: Dict[str, Any] = {"access_token": str(token)}
    refresh = payload.get("refresh_token") or inner.get("refresh_token") or inner.get("refreshToken")
    if refresh:
        out["refresh_token"] = str(refresh)
    if payload.get("expires_in") or inner.get("expires_in"):
        out["expires_in"] = payload.get("expires_in") or inner.get("expires_in")
    return out


@router.get("/stores/oauth/authorize")
async def oauth_authorize(
    request: Request,
    platform: str = Query(...),
    app_key: str = Query(""),
    app_secret: str = Query(""),
    store_name: str = Query(""),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """构造平台授权 URL 并 302 跳转（Tier 2）；先落 pending 店铺与应用凭据"""
    manager = _get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    platform = str(platform or "").strip().lower()
    if platform not in _OAUTH_SUPPORTED:
        raise HTTPException(status_code=400, detail=f"平台 {platform} 不支持 OAuth 直连（亚马逊为自授权，请走 Tier 1 录入 refresh_token）")
    if not (app_key and app_secret):
        raise HTTPException(status_code=400, detail="app_key / app_secret 必填")
    conn = manager.create_store(
        platform,
        str(store_name or "").strip() or f"{platform} OAuth 店铺",
        credentials={"app_key": app_key, "app_secret": app_secret},
        user_id=user_id,
        status="pending",
    )
    state = str(uuid.uuid4().hex)
    manager.oauth_state_set(
        state,
        {"platform": platform, "store_id": conn.store_id, "user_id": user_id, "created_at": time.time()},
    )
    url = _oauth_authorize_url(platform, app_key, _oauth_callback_uri(request), state)
    return RedirectResponse(url, status_code=302)


@router.get("/stores/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
):
    """平台授权回调：校验 state（一次性/防 CSRF）→ 换 token → 更新店铺 → 302 回前端"""
    manager = _get_store_manager()
    meta = manager.oauth_state_pop(state)
    if not meta:
        raise HTTPException(status_code=400, detail="无效的 state（缺失或已使用）")
    if time.time() - float(meta.get("created_at") or 0) > _OAUTH_STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="state 已过期，请重新发起授权")
    platform = str(meta.get("platform") or "")
    store_id = str(meta.get("store_id") or "")
    user_id = str(meta.get("user_id") or "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")
    try:
        creds = manager.resolve_credentials(platform, store_id, user_id)
        token_data = await _oauth_exchange_token(platform, creds.app_key, creds.app_secret, code, _oauth_callback_uri(request))
        update = {"access_token": token_data.get("access_token") or "", "status": "active", "last_error": ""}
        if token_data.get("refresh_token"):
            update["refresh_token"] = token_data.get("refresh_token")
        expires = token_data.get("expires_in")
        fields: Dict[str, Any] = {"status": "active", "last_error": ""}
        if expires:
            fields["token_expires_at"] = time.time() + int(expires)
        manager.update_store(store_id, user_id=user_id, credentials=update, **fields)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        manager.update_store(store_id, user_id=user_id, status="error", last_error=str(exc))
        return RedirectResponse("/collaboration/canvas?store_oauth=error", status_code=302)
    return RedirectResponse("/collaboration/canvas?store_oauth=ok", status_code=302)


# ==================== 工作流 CRUD ====================


@router.get("/workflows")
async def list_workflows(
    category: Optional[str] = Query(None, description="按分类过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """列出工作流"""
    storage = _get_storage()
    ws_status = WorkflowStatus(status) if status else None
    workflows = storage.list_workflows(category=category, status=ws_status, limit=limit, offset=offset)
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


@router.post("/workflows")
async def create_workflow(data: Dict[str, Any] = Body(...)):
    """创建工作流"""
    storage = _get_storage()
    try:
        # 如果前端没有提供 id，则生成一个新的 UUID
        if "id" not in data or not data["id"]:
            import uuid

            data["id"] = str(uuid.uuid4())

        workflow = WorkflowDefinition.from_dict(data)
        workflow.created_at = time.time()
        workflow.updated_at = time.time()
        storage.save_workflow(workflow)
        return {"workflow": workflow.to_dict(), "message": "工作流创建成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建工作流失败: {str(e)}")


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """获取工作流详情"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"workflow": workflow.to_dict()}


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """更新工作流"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    try:
        workflow = WorkflowDefinition.from_dict(data)
        workflow.id = workflow_id
        workflow.updated_at = time.time()
        storage.save_workflow(workflow)
        return {"workflow": workflow.to_dict(), "message": "工作流更新成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流失败: {str(e)}")


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """删除工作流"""
    storage = _get_storage()
    result = storage.delete_workflow(workflow_id)
    if not result:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"message": "工作流删除成功"}


@router.get("/workflows/search/{query}")
async def search_workflows(query: str):
    """搜索工作流"""
    storage = _get_storage()
    workflows = storage.search_workflows(query)
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


# ==================== 工作流验证 ====================


@router.post("/workflows/{workflow_id}/validate")
async def validate_workflow(workflow_id: str):
    """验证工作流"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    validator = get_dag_validator()
    result = validator.validate(workflow.nodes, workflow.edges)
    return {
        "is_valid": result.is_valid,
        "has_cycle": result.has_cycle,
        "has_start": result.has_start,
        "has_end": result.has_end,
        "errors": result.errors,
        "warnings": result.warnings,
    }


# ==================== 工作流执行 ====================


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    inputs: Dict[str, Any] = Body(default={}),
    user_id: Optional[str] = Body(default=None),
    agent_id: Optional[str] = Body(default=None),
):
    """执行工作流"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # 获取外部系统引用（从 Agent 实例）
    memory_manager = None
    context_pool = None
    emotion_module = None
    crystallizer = None

    # 尝试获取 Agent 实例：优先使用指定的 agent_id，否则尝试默认
    agent = None
    if agent_id:
        agent = get_agent_instance(agent_id)
    if agent is None:
        # 尝试获取默认 Agent
        agent = get_agent_instance("default")

    if agent:
        memory_manager = getattr(agent, "memory_manager", None)
        # context_pool: 尝试从 context_orchestrator 获取，或使用 Agent 的 context_pool 属性
        context_pool = getattr(agent, "context_pool", None)
        if context_pool is None and hasattr(agent, "context_orchestrator"):
            # context_orchestrator 可能有 pool 属性
            context_pool = getattr(agent.context_orchestrator, "pool", None)
        # emotion_module: 从 memory_manager 获取
        if memory_manager:
            emotion_module = getattr(memory_manager, "_emotion_module", None)
        crystallizer = getattr(agent, "crystallizer", None)

    # 降级机制：当 Agent 不可用时，创建默认实例
    # memory_manager
    if memory_manager is None:
        try:
            from neurova.cognitive_layers.memory_layer.manager import MemoryManager

            memory_manager = MemoryManager(agent_id=agent_id or "default", user_id=user_id or "default")
            logger.info("Agent 不可用，已创建默认 MemoryManager 用于 $memory 变量解析")
        except Exception as e:
            logger.warning("创建默认 MemoryManager 失败: %s", e)

    # emotion_module: 优先从 memory_manager 提取，否则创建独立实例
    if emotion_module is None:
        if memory_manager and hasattr(memory_manager, "_emotion_module"):
            emotion_module = memory_manager._emotion_module
        if emotion_module is None:
            try:
                from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

                emotion_module = EmotionModule(db_path=None)  # 纯内存模式
                logger.info("Agent 不可用，已创建默认 EmotionModule 用于 $emotion 变量解析")
            except Exception as e:
                logger.warning("创建默认 EmotionModule 失败: %s", e)

    # crystallizer: 尝试创建带默认存储引擎的结晶器
    if crystallizer is None:
        try:
            from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
            from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

            engine = CognitiveStorageEngine(agent_id=agent_id or "default")
            crystallizer = PatternCrystallizer(engine=engine)
            logger.info("Agent 不可用，已创建默认 PatternCrystallizer 用于 $crystal 变量解析")
        except Exception as e:
            logger.warning("创建默认 PatternCrystallizer 失败: %s", e)

    # context_pool: 保持原有降级逻辑
    if context_pool is None:
        try:
            from neurova.context_pool import ContextPool

            context_pool = ContextPool(user_id=user_id or "default", agent_id=agent_id or "default")
            logger.info("Agent 不可用，已创建默认 ContextPool 用于 $context 变量解析")
        except Exception as e:
            logger.warning("创建默认 ContextPool 失败: %s", e)

    executor = get_workflow_executor()
    instance = await executor.execute(
        workflow=workflow,
        inputs=inputs,
        user_id=user_id,
        agent_id=agent_id,
        memory_manager=memory_manager,
        context_pool=context_pool,
        emotion_module=emotion_module,
        crystallizer=crystallizer,
    )

    # 保存执行实例
    storage.save_execution(instance)

    return {
        "instance": {
            "id": instance.id,
            "workflow_id": instance.workflow_id,
            "status": instance.status.value,
            "inputs": instance.inputs,
            "outputs": instance.outputs,
            "node_results": {k: v.__dict__ for k, v in instance.node_results.items()},
            "variables": instance.variables,
            "started_at": instance.started_at,
            "finished_at": instance.finished_at,
            "duration": instance.duration,
            "error": instance.error,
        }
    }


@router.get("/executions")
async def list_executions(
    workflow_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """列出执行记录"""
    storage = _get_storage()
    ws_status = WorkflowStatus(status) if status else None
    executions = storage.list_executions(workflow_id=workflow_id, status=ws_status, limit=limit, offset=offset)
    return {
        "executions": [
            {
                "id": e.id,
                "workflow_id": e.workflow_id,
                "status": e.status.value,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
                "duration": e.duration,
                "error": e.error,
            }
            for e in executions
        ]
    }


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    """获取执行详情"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return {
        "execution": {
            "id": execution.id,
            "workflow_id": execution.workflow_id,
            "status": execution.status.value,
            "inputs": execution.inputs,
            "outputs": execution.outputs,
            "node_results": {k: v.__dict__ for k, v in execution.node_results.items()},
            "variables": execution.variables,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "duration": execution.duration,
            "error": execution.error,
        }
    }


# ==================== 节点注册表 ====================


@router.get("/nodes")
async def list_nodes(
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    """列出所有已注册节点"""
    registry = get_node_registry()
    # 确保内置节点 + 适配器节点（工具/技能/MCP/ComfyUI/电商/短剧视频）均已注册
    registry.ensure_builtin()
    registry.sync_all()

    if category:
        nodes = registry.list_by_category(category)
    elif source:
        nodes = registry.list_by_source(source)
    else:
        nodes = registry.list_all()

    return {
        "nodes": [
            {
                "type": n.type,
                "label": n.label,
                "icon": n.icon,
                "category": n.category,
                "description": n.description,
                "source": n.source,
                "version": n.version,
                "tags": n.tags,
                # 端口与配置表单（画布动态节点库渲染用）
                "inputs": [_port_to_dict(p) for p in (n.inputs or [])],
                "outputs": [_port_to_dict(p) for p in (n.outputs or [])],
                "sub_blocks": [_sub_block_to_dict(b) for b in (n.sub_blocks or [])],
            }
            for n in nodes
        ],
        "total": len(nodes),
    }


@router.get("/nodes/search/{query}")
async def search_nodes(query: str):
    """搜索节点"""
    registry = get_node_registry()
    results = registry.search(query)
    return {
        "nodes": [
            {
                "type": n.type,
                "label": n.label,
                "icon": n.icon,
                "category": n.category,
                "description": n.description,
                "source": n.source,
                "tags": n.tags,
            }
            for n in results
        ],
        "total": len(results),
    }


@router.post("/nodes/sync")
async def sync_nodes():
    """同步所有节点（工具/技能/MCP）"""
    registry = get_node_registry()
    result = registry.sync_all()
    return {"sync_result": result, "message": "节点同步完成"}


@router.get("/nodes/stats")
async def get_node_stats():
    """获取节点统计"""
    registry = get_node_registry()
    registry.ensure_builtin()
    return {"summary": registry.get_summary()}


@router.get("/nodes/{node_type:path}")
async def get_node(node_type: str):
    """获取节点定义"""
    registry = get_node_registry()
    node = registry.get(node_type)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {
        "node": {
            "type": node.type,
            "label": node.label,
            "icon": node.icon,
            "category": node.category,
            "description": node.description,
            "sub_blocks": [_sub_block_to_dict(s) for s in node.sub_blocks],
            "inputs": [_port_to_dict(i) for i in node.inputs],
            "outputs": [_port_to_dict(o) for o in node.outputs],
            "source": node.source,
            "version": node.version,
            "tags": node.tags,
        }
    }


# ==================== 工作流扩展 API ====================


@router.post("/workflows/{workflow_id}/duplicate")
async def duplicate_workflow(workflow_id: str):
    """复制工作流"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")

    try:
        # 创建副本
        new_workflow = WorkflowDefinition(
            id=f"{workflow_id}_copy_{int(time.time())}",
            name=f"{existing.name} (副本)",
            description=existing.description,
            version=existing.version,
            nodes=existing.nodes.copy(),
            edges=existing.edges.copy(),
            variables=existing.variables.copy(),
            tags=existing.tags.copy(),
            category=existing.category,
            author=existing.author,
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,  # 副本总是草稿状态
            template=existing.template,
            public=False,  # 副本默认不公开
            metadata=existing.metadata.copy(),
        )
        storage.save_workflow(new_workflow)
        return {"workflow": new_workflow.to_dict(), "message": "工作流复制成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"复制工作流失败: {str(e)}")


@router.get("/workflows/{workflow_id}/definition")
async def get_workflow_definition(workflow_id: str):
    """获取工作流定义"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    return {
        "nodes": [n.__dict__ for n in workflow.nodes],
        "edges": [e.__dict__ for e in workflow.edges],
        "variables": [v.__dict__ for v in workflow.variables],
    }


@router.put("/workflows/{workflow_id}/definition")
async def update_workflow_definition(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """更新工作流定义（节点/边/变量）"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")

    try:
        # 更新节点
        if "nodes" in data:
            existing.nodes = [WorkflowNode(**n) for n in data["nodes"]]

        # 更新边
        if "edges" in data:
            existing.edges = [WorkflowEdge(**e) for e in data["edges"]]

        # 更新变量
        if "variables" in data:
            existing.variables = [WorkflowVariable(**v) for v in data["variables"]]

        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "工作流定义更新成功", "workflow": existing.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流定义失败: {str(e)}")


@router.put("/workflows/{workflow_id}/viewport")
async def save_workflow_viewport(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """保存工作流视口状态"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")

    try:
        # 保存视口状态到 metadata
        existing.metadata["viewport"] = {"x": data.get("x", 0), "y": data.get("y", 0), "zoom": data.get("zoom", 1)}
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "视口状态保存成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存视口状态失败: {str(e)}")


@router.post("/workflows/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """发布工作流（P2：编译 AgentManifest 并落 agents 记录，chat 页可直接选用）"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")

    try:
        # 验证工作流
        validator = get_dag_validator()
        validation_result = validator.validate(existing.nodes, existing.edges)

        if not validation_result.is_valid:
            raise HTTPException(status_code=400, detail=f"工作流验证失败: {', '.join(validation_result.errors)}")

        # P2 Step 3 — 编译 AgentManifest 并持久化 agent 记录（幂等 upsert）
        from neurova.agent.workflow_agent import compile_workflow_agent, manifest_to_agent_info

        manifest = compile_workflow_agent(existing)
        agent_info = manifest_to_agent_info(manifest)
        storage.save_agent(agent_info)

        # 更新状态为已发布
        existing.status = WorkflowStatus.PUBLISHED
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {
            "code": 0,
            "message": "工作流发布成功",
            "data": {
                "workflow": existing.to_dict(),
                "agent": {
                    "agent_id": agent_info.agent_id,
                    "name": agent_info.name,
                    "role": agent_info.role,
                    "capabilities": agent_info.capabilities,
                    "metadata": agent_info.metadata,
                },
            },
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"发布失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"发布工作流失败: {str(e)}")


# ==================== 执行控制 API ====================


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    """取消执行"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    try:
        executor = get_workflow_executor()
        success = executor.cancel(execution_id)
        if success:
            # 更新执行状态
            execution.status = WorkflowStatus.CANCELLED
            execution.finished_at = time.time()
            execution.duration = execution.finished_at - execution.started_at
            storage.save_execution(execution)
            return {"message": "执行已取消"}
        else:
            raise HTTPException(status_code=400, detail="取消执行失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取消执行失败: {str(e)}")


@router.post("/executions/{execution_id}/resume")
async def resume_execution(
    execution_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """恢复执行（人工审批后）"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    if execution.status != WorkflowStatus.PAUSED:
        raise HTTPException(status_code=400, detail="只能恢复暂停的执行")

    try:
        executor = get_workflow_executor()
        success = executor.resume(execution_id)
        if success:
            # 更新执行状态
            execution.status = WorkflowStatus.RUNNING
            storage.save_execution(execution)
            return {"message": "执行已恢复"}
        else:
            raise HTTPException(status_code=400, detail="恢复执行失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"恢复执行失败: {str(e)}")


# ==================== 团队 Agent API ====================


@router.get("/agents")
async def list_agents(
    flow_id: Optional[str] = Query(None, description="按工作流过滤"),
    include_archived: bool = Query(False, description="是否包含已归档"),
):
    """列出团队 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager

        manager = get_agent_manager()
        agents = manager.list_agents(flow_id=flow_id, include_archived=include_archived)
        return {"agents": [a.__dict__ for a in agents], "total": len(agents)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取 Agent 列表失败: {str(e)}")


@router.post("/agents")
async def create_agent(data: Dict[str, Any] = Body(...)):
    """创建临时团队 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager

        manager = get_agent_manager()

        name = data.get("name")
        role = data.get("role")
        if not name or not role:
            raise HTTPException(status_code=400, detail="名称和角色是必填字段")

        import logging

        logger = get_logger(__name__)
        logger.error("DEBUG: name=%s, role=%s, manager=%s", name, role, manager)

        agent = manager.create_agent(name=name, role=role, config=data.get("config", {}), flow_id=data.get("flow_id"))
        from starlette.responses import JSONResponse

        # 构建响应数据
        agent_data = {
            "id": str(agent.agent_id) if hasattr(agent, "agent_id") else None,
            "name": str(agent.name) if hasattr(agent, "name") else name,
            "role": str(agent.role) if hasattr(agent, "role") else role,
            "config": dict(agent.config) if hasattr(agent, "config") else data.get("config", {}),
            "flow_id": str(agent.flow_id) if hasattr(agent, "flow_id") else data.get("flow_id"),
            "status": str(agent.status) if hasattr(agent, "status") else "active",
            "created_at": float(agent.created_at) if hasattr(agent, "created_at") else None,
        }
        return JSONResponse(content={"agent": agent_data, "message": "Agent 创建成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建 Agent 失败: {str(e)}")


@router.post("/agents/{agent_id}/archive")
async def archive_agent(agent_id: str):
    """归档 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager

        manager = get_agent_manager()
        success = manager.archive_agent(agent_id)
        if success:
            return {"message": "Agent 已归档"}
        else:
            raise HTTPException(status_code=404, detail="Agent 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"归档 Agent 失败: {str(e)}")


@router.post("/agents/{agent_id}/restore")
async def restore_agent(agent_id: str):
    """恢复 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager

        manager = get_agent_manager()
        success = manager.restore_agent(agent_id)
        if success:
            return {"message": "Agent 已恢复"}
        else:
            raise HTTPException(status_code=404, detail="Agent 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"恢复 Agent 失败: {str(e)}")


# ==================== 模板 API ====================


@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(None, description="按分类过滤"),
):
    """列出工作流模板"""
    storage = _get_storage()
    try:
        templates = storage.list_templates(category=category)
        return {"templates": [t.to_dict() for t in templates], "total": len(templates)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取模板列表失败: {str(e)}")


@router.post("/templates")
async def create_template(data: Dict[str, Any] = Body(...)):
    """创建工作流模板"""
    storage = _get_storage()
    try:
        # 基于现有工作流创建模板
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            raise HTTPException(status_code=400, detail="workflow_id 是必填字段")

        existing = storage.get_workflow(workflow_id)
        if not existing:
            raise HTTPException(status_code=404, detail="工作流不存在")

        # 创建模板
        template = WorkflowDefinition(
            id=f"tmpl_{int(time.time())}",
            name=data.get("name", existing.name),
            description=data.get("description", existing.description),
            version=existing.version,
            nodes=existing.nodes.copy(),
            edges=existing.edges.copy(),
            variables=existing.variables.copy(),
            tags=data.get("tags", existing.tags),
            category=data.get("category", existing.category),
            author=data.get("author", existing.author),
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
            template=True,  # 标记为模板
            public=data.get("public", False),
            metadata=existing.metadata.copy(),
        )
        storage.save_workflow(template)
        from starlette.responses import JSONResponse

        return JSONResponse(content={"template": template.to_dict(), "message": "模板创建成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建模板失败: {str(e)}")


@router.post("/templates/{template_id}/instantiate")
async def instantiate_template(template_id: str, data: Dict[str, Any] = Body(...)):
    """从模板创建工作流"""
    storage = _get_storage()
    try:
        # 获取模板
        template = storage.get_workflow(template_id)
        if not template or not template.template:
            raise HTTPException(status_code=404, detail="模板不存在")

        # 创建新工作流
        new_workflow = WorkflowDefinition(
            id=f"wf_{int(time.time())}",
            name=data.get("name", f"{template.name} - 实例"),
            description=template.description,
            version=template.version,
            nodes=template.nodes.copy(),
            edges=template.edges.copy(),
            variables=template.variables.copy(),
            tags=template.tags.copy(),
            category=template.category,
            author=data.get("author", "user"),
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,
            template=False,
            public=False,
            metadata=template.metadata.copy(),
        )

        # 应用变量覆盖
        if "variables" in data:
            for var in new_workflow.variables:
                if var.name in data["variables"]:
                    var.default_value = data["variables"][var.name]

        storage.save_workflow(new_workflow)
        from starlette.responses import JSONResponse

        return JSONResponse(
            content={"workflow": new_workflow.to_dict(), "message": "从模板创建工作流成功"}, status_code=201
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"从模板创建工作流失败: {str(e)}")


# ==================== 统计 ====================


@router.get("/stats")
async def get_stats():
    """获取 Neurflow 统计信息"""
    storage = _get_storage()
    registry = get_node_registry()
    registry.ensure_builtin()
    return {"storage": storage.get_statistics(), "nodes": registry.get_summary()}


# ==================== ComfyUI 集成 ====================


class ComfyUIExecuteRequest(BaseModel):
    """ComfyUI 单节点执行请求"""

    class_type: str
    config: Dict[str, Any] = {}
    inputs: Dict[str, Any] = {}


# 注：旧的 POST /comfyui/import「定义优先」导入端点已下线。
# 工作流 = 无限画布工作流，ComfyUI 导入统一走
# POST /v1/collaboration/comfyui/import-canvas 落为可编辑画布快照，
# WorkflowDefinition 只是画布执行时的内部编译产物。


@router.get("/comfyui/status")
async def get_comfyui_status():
    """检查 ComfyUI 服务可用性"""
    from neurova.collaboration.neurflow.comfyui_client import get_comfyui_client

    client = get_comfyui_client()
    return {"available": client.is_available(), "host": client.host}


@router.post("/comfyui/execute")
async def execute_comfyui_node_endpoint(request: ComfyUIExecuteRequest):
    """直接执行单个 ComfyUI 节点（提交 prompt 到 ComfyUI /prompt）"""
    from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

    result = await _execute_comfyui_node(f"comfyui:{request.class_type}", request.config, request.inputs)
    return result


# ==================== P0 Step 4 — 调试 API ====================


from neurova.collaboration.neurflow.execution_engine import DebugSession  # noqa: E402
from neurova.collaboration.neurflow.execution_engine import get_node_mocks as _get_node_mocks  # noqa: E402


# 全局注册表：execution_id → DebugSession（in-memory，仅调试用）
_DEBUG_SESSIONS: Dict[str, DebugSession] = {}

# 全局注册表：node_id → mock_output（in-memory，调试用）


class BreakpointRequest(BaseModel):
    """设置断点请求体"""

    breakpoints: list[str] = []
    replace: bool = True


class ResumeRequest(BaseModel):
    """恢复执行请求体"""

    step: Optional[str] = None  # None | "in" | "over" | "out"


class MockNodeRequest(BaseModel):
    """设置节点 mock 输出请求体"""

    mock_output: Optional[Any] = None
    clear: bool = False


@router.post("/executions/{execution_id}/breakpoint")
async def set_breakpoints(
    execution_id: str,
    body: BreakpointRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """为指定 execution 设置/追加断点集合。"""
    session = _DEBUG_SESSIONS.setdefault(execution_id, DebugSession())
    if body.replace:
        session.breakpoints = set(body.breakpoints)
    else:
        session.breakpoints.update(body.breakpoints)
    return {
        "execution_id": execution_id,
        "breakpoints": sorted(session.breakpoints),
        "count": len(session.breakpoints),
    }


@router.post("/executions/{execution_id}/debug/resume")
async def resume_debug_execution(
    execution_id: str,
    body: ResumeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """恢复调试暂停中的执行；可选 step 模式（in/over/out）。

    路径区分于 /executions/{id}/resume（人工审批恢复）——两者同名会导致
    FastAPI 路由遮蔽（先注册者独占，调试恢复成死代码）。
    """
    session = _DEBUG_SESSIONS.get(execution_id)
    if not session:
        raise HTTPException(status_code=404, detail="未找到该 execution 的调试会话")
    if body.step is not None and body.step not in ("in", "over", "out"):
        raise HTTPException(status_code=400, detail="step 必须为 in/over/out 之一")
    session.step_mode = body.step
    session.resume()
    return {"execution_id": execution_id, "resumed": True, "step_mode": session.step_mode}


@router.get("/executions/{execution_id}/variables")
async def get_execution_variables(
    execution_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取当前执行实例的所有变量（含 inputs/variables/node_results）。"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行实例不存在")
    return {
        "execution_id": execution_id,
        "inputs": execution.inputs,
        "variables": execution.variables,
        "node_results": {
            nid: {
                "status": nr.status,
                "output": nr.output,
            }
            for nid, nr in execution.node_results.items()
        },
    }


@router.put("/nodes/{node_id}/mock")
async def set_node_mock(
    node_id: str,
    body: MockNodeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """为节点设置 mock 输出；clear=true 时清空（恢复真实执行）。"""
    mocks = _get_node_mocks()
    if body.clear:
        mocks.pop(node_id, None)
        return {"node_id": node_id, "mocked": False}
    mocks[node_id] = body.mock_output
    return {"node_id": node_id, "mocked": True}


# ==================== P1 Step 4b — Webhook 入站触发（薄壳） ====================


from fastapi import Request  # noqa: E402
from neurova.collaboration.neurflow import webhook_ingress  # noqa: E402
from neurova.core.trigger_rate_limiter import TriggerRateLimiter  # noqa: E402

# 每 trigger_id 缓存的限流桶（跨请求共享；rate_limiter_for 消费）
_WEBHOOK_RATE_LIMITERS: Dict[str, TriggerRateLimiter] = {}


def _webhook_ingress_deps() -> Dict[str, Any]:
    """装配 webhook_ingress 默认 deps（trigger/workflow 加载 + 解密 + 执行）。

    安全语义：仅 PUBLISHED 状态的工作流可被 webhook 派发。
    """
    from neurova.core.trigger_rate_limiter import TriggerRateLimiter
    from neurova.llm.providers.secret_store import decrypt_api_key
    from neurova.collaboration.neurflow.models import WorkflowStatus

    def load_trigger(tid: str):
        return _get_storage().get_trigger(tid)

    def load_published_workflow(ref: str):
        storage = _get_storage()
        wf = storage.get_workflow(ref)
        if wf is not None and wf.status == WorkflowStatus.PUBLISHED:
            return wf
        return None

    async def run_workflow(workflow, inputs):
        return await get_workflow_executor().execute(workflow=workflow, inputs=inputs)

    def rate_limiter_for(trigger):
        """按 trigger_id 缓存 limiter（跨请求共享桶，限流才生效）。"""
        tid = getattr(trigger, "id", "")
        limiter = _WEBHOOK_RATE_LIMITERS.get(tid)
        if limiter is None:
            limiter = TriggerRateLimiter(getattr(trigger, "rate_limit_per_minute", None))
            _WEBHOOK_RATE_LIMITERS[tid] = limiter
        return limiter

    return {
        "load_trigger": load_trigger,
        "load_published_workflow": load_published_workflow,
        "decrypt_secret": decrypt_api_key,
        "run_workflow": run_workflow,
        "rate_limiter_for": rate_limiter_for,
    }


webhook_ingress.set_deps_provider(_webhook_ingress_deps)


def get_workflow_agent_deps() -> Dict[str, Any]:
    """遗留③a：workflow_agent 桥接 deps 工厂（tool_executor 首次调用时装配）。

    load_agent / load_published_workflow 走 Neurflow storage；
    run_workflow 走 WorkflowExecutor（单租户默认——chat 请求级用户隔离
    在 memory 层 ContextVar，工作流执行链路后续按需透传）。
    """
    from neurova.collaboration.neurflow.models import WorkflowStatus

    def load_agent(aid: str):
        return _get_storage().get_agent(aid)

    def load_published_workflow(ref: str):
        storage = _get_storage()
        wf = storage.get_workflow(ref)
        if wf is not None and wf.status == WorkflowStatus.PUBLISHED:
            return wf
        return None

    async def run_workflow(workflow, inputs):
        return await get_workflow_executor().execute(workflow=workflow, inputs=inputs)

    return {
        "load_agent": load_agent,
        "load_published_workflow": load_published_workflow,
        "run_workflow": run_workflow,
    }


# 遗留③a：模块导入时一次性装配（tool_executor 的 run_workflow_agent 分支消费）
from neurova.agent.workflow_agent import set_workflow_agent_deps as _set_wa_deps  # noqa: E402

_set_wa_deps(get_workflow_agent_deps)


# P0-7/N4：入站 body 上限（1MB）——限流在验签后，但超大 body 会先于一切
# 消耗内存与带宽，必须在读 body 前按 Content-Length 硬拒
_WEBHOOK_MAX_BODY_BYTES = 1024 * 1024


@router.post("/triggers/webhook/{trigger_id}/receive")
async def receive_webhook_trigger(trigger_id: str, request: Request):
    """外部系统入站触发工作流（HMAC 验签 + 重放防护 + 限流 + 派发；逻辑在 webhook_ingress）。

    投递审计：无论成败均落 webhook_deliveries（P1 Step 7 表）。
    """
    declared = request.headers.get("content-length")
    try:
        if declared and int(declared) > _WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="PAYLOAD_TOO_LARGE")
    except ValueError:
        pass

    payload = await request.body()
    if len(payload) > _WEBHOOK_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="PAYLOAD_TOO_LARGE")

    header_sig = request.headers.get("X-Hub-Signature-256")
    header_ts = request.headers.get("X-Neurova-Timestamp")
    try:
        result = await webhook_ingress.handle_webhook_ingress(
            trigger_id, payload, header_sig, timestamp_header=header_ts
        )
    except webhook_ingress.IngressRejected as e:
        sig_valid = e.reason not in ("INVALID_SIGNATURE", "TRIGGER_NOT_FOUND")
        try:
            _get_storage().save_delivery(
                trigger_id=trigger_id,
                signature_valid=sig_valid,
                execution_id=None,
                status_code=e.status_code,
            )
        except Exception:
            logger.warning("delivery record failed (rejected path): %s", trigger_id)
        raise HTTPException(status_code=e.status_code, detail=e.reason)

    try:
        _get_storage().save_delivery(
            trigger_id=trigger_id,
            signature_valid=True,
            execution_id=(result.get("data") or {}).get("execution_id"),
            status_code=200,
        )
    except Exception:
        logger.warning("delivery record failed (success path): %s", trigger_id)
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
    storage = _get_storage()
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
    import secrets as _secrets

    from neurova.llm.providers.secret_store import encrypt_api_key

    storage = _get_storage()
    if not storage.get_workflow(workflow_id):
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
        secret_hash = NeurflowStorage.hash_trigger_secret(secret_plain)
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
            logger.warning("cron trigger register deferred: %s", e)

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
    storage = _get_storage()
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
    storage = _get_storage()
    trigger = storage.get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="触发器不存在")

    from neurova.collaboration.neurflow.models import WorkflowStatus

    wf = storage.get_workflow(trigger.workflow_id)
    if wf is None or wf.status != WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=404, detail="工作流未发布")

    async def _run(workflow, inputs):
        return await get_workflow_executor().execute(workflow=workflow, inputs=inputs)

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
    storage = _get_storage()
    return {"code": 0, "data": storage.list_deliveries(trigger_id, limit=limit)}


# ==================== P2 遗留② — 版本 REST API ====================


@router.get("/workflows/{workflow_id}/versions")
async def list_workflow_versions_api(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """工作流版本历史（倒序；内容指纹快照）。"""
    storage = _get_storage()
    if not storage.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"code": 0, "data": storage.list_workflow_versions(workflow_id)}


@router.post("/workflows/{workflow_id}/versions/{version}/rollback")
async def rollback_workflow_api(
    workflow_id: str,
    version: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """回滚到指定版本（状态保持当前值；回滚本身产生新版本）。"""
    storage = _get_storage()
    if not storage.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="工作流不存在")
    if not storage.rollback_workflow(workflow_id, version):
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "code": 0,
        "message": "rollback ok",
        "data": {"workflow": storage.get_workflow(workflow_id).to_dict()},
    }
