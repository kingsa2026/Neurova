"""Store connections and OAuth routes; aggregator names remain runtime patch seams."""
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from neurova.api.auth import get_current_user_or_default

router = APIRouter()

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
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    stores = manager.list_stores(platform or "", user_id=user_id)
    return {"stores": [manager.mask(s) for s in stores], "total": len(stores)}


@router.post("/stores")
async def create_store(
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """连接店铺：注册表 + 凭据入库（Tier 1 手工录入）"""
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    platform = str(data.get("platform") or "").strip()
    store_name = str(data.get("store_name") or "").strip()
    if not platform or not store_name:
        raise HTTPException(status_code=400, detail="platform 与 store_name 必填")
    if platform not in ("amazon", "taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"):
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    fields = {k: v for k, v in data.items() if k in api._STORE_FIELD_KEYS and k != "store_name"}
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
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
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
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    fields = {k: v for k, v in data.items() if k in api._STORE_FIELD_KEYS}
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
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if not manager.delete_store(store_id, user_id=user_id):
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    return {"message": "店铺已删除"}


@router.post("/stores/{store_id}/test")
async def test_store_connection(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """连接测试（只读探针；仅限归属用户）"""
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if manager.get_store(store_id, user_id=user_id) is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    result = await manager.test_connection(store_id, user_id=user_id)
    return {"result": result}


@router.post("/stores/{store_id}/refresh")
async def refresh_store_token(store_id: str, current_user: Dict[str, Any] = Depends(get_current_user_or_default)):
    """强制刷新令牌（仅限归属用户）"""
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    if manager.get_store(store_id, user_id=user_id) is None:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    result = await manager.refresh_token(store_id, user_id=user_id)
    return {"result": result}


# ==================== Tier 2 OAuth（一键授权跳转） ====================
# 依据 §2（2026-08-29 复核）：
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
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    user_id = str(current_user.get("user_id") or "")
    platform = str(platform or "").strip().lower()
    if platform not in api._OAUTH_SUPPORTED:
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
    url = api._oauth_authorize_url(platform, app_key, api._oauth_callback_uri(request), state)
    return RedirectResponse(url, status_code=302)


@router.get("/stores/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
):
    """平台授权回调：校验 state（一次性/防 CSRF）→ 换 token → 更新店铺 → 302 回前端"""
    from neurova.api.endpoints import neurflow_api as api

    manager = api._get_store_manager()
    meta = manager.oauth_state_pop(state)
    if not meta:
        raise HTTPException(status_code=400, detail="无效的 state（缺失或已使用）")
    if time.time() - float(meta.get("created_at") or 0) > api._OAUTH_STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="state 已过期，请重新发起授权")
    platform = str(meta.get("platform") or "")
    store_id = str(meta.get("store_id") or "")
    user_id = str(meta.get("user_id") or "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")
    try:
        creds = manager.resolve_credentials(platform, store_id, user_id)
        token_data = await api._oauth_exchange_token(platform, creds.app_key, creds.app_secret, code, api._oauth_callback_uri(request))
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


