from __future__ import annotations

"""
设置管理接口 - Settings Endpoint

功能:
1. 获取全局设置 (GET /api/v1/settings)
2. 更新全局设置 (PUT /api/v1/settings)
3. 获取特定设置 (GET /api/v1/settings/{key})
4. 更新特定设置 (PUT /api/v1/settings/{key})
5. 获取 CORS 配置 (GET /api/v1/settings/cors)
6. 更新 CORS 配置 (PUT /api/v1/settings/cors)

路由顺序说明：/cors 必须在 /{key} 之前注册，否则 "cors" 会被
路径参数 {key} 捕获（GET /cors → get_setting("cors") → 404）。
"""

import json
from neurova.core.logger import get_logger
import time
import uuid
from pathlib import Path as FilePath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api import cors_policy
from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/settings")

# 默认设置（平铺 legacy 键，供 /{key} 兼容读写）
_default_settings = {
    "theme": "dark",
    # 2026-10-12 §6-167：`language` 一格退役。它先前**同时**是这张平铺表的一格与
    # `core/app_settings.py` `GENERAL_DEFAULTS` 的一格——同一个面把同一个问题回显两遍
    # （顶层一份、general 一份），而两份的读者都是 0 处。语言的起点现在只在语言层
    # （`GET/PUT /api/v1/language/preferences/default`，写面仅管理员）。
    "auto_save": True,
    "notifications": True,
    "stream_mode": True,
    # 2026-09-10：max_tokens/temperature 两键移除——全链零消费的死参数；
    # 温度已迁记忆设置 llm.temperature（全局默认生成温度，agent 显式值优先）
    # 2026-09-12 更正：max_tokens 有真实消费方（openai_loop 每请求读
    # llm_client.config.max_tokens），以 advanced.max_output_tokens 形式
    # 回归（见 core/app_settings.py，全局默认、显式 agent 配置优先）。
}

# 结构化 section（真持久化，data/app_settings.json——替换内存 stub：
# 此前高级选项卡保存即丢、读取形状错位，整页为装饰性）
_SETTINGS_SECTIONS = ("general", "security", "storage", "advanced", "routing")

#: 已退役的语言键：本面**既不读也不收**。
#: 只删默认表是不够的——`PUT /settings` 的 body 是 `Dict[str, Any]`，没有任何闭集校验
#: （实测旧调用方写 `"zh_CN"` 这种下划线码也照样回 200），所以旧键能被原样写回盘上、
#: 再被 `GET` 原样回显，得到一根**只写不读**的新断链，比退役前更糟。
#: 按教义第 2 条，退役后的键必须以显式 400 ＋ 去处暴露，而不是静默收下。
RETIRED_LANGUAGE_KEY = "language"
#: 拒因里必须带的去处——不带给谁去，旧调用方只会重试，不会知道自己该改指哪里。
LANGUAGE_MIGRATION_POINTER = (
    "语言的默认值已收口到语言层：开箱默认（影响所有还没选过语言的人，仅管理员可写）"
    " PUT /api/v1/language/preferences/default，本人偏好 PUT /api/v1/language/preferences/mine")


def _rejectRetiredLanguageKey(key: str, where: str) -> None:
    if key == RETIRED_LANGUAGE_KEY:
        raise HTTPException(
            status_code=400,
            detail=f"{where} 不再接受 `{RETIRED_LANGUAGE_KEY}` 这一格：{LANGUAGE_MIGRATION_POINTER}")


def _dropRetiredLanguageKeys(settings: Dict[str, Any]) -> Dict[str, Any]:
    """把盘上残留的旧键从**读数**里摘掉，但不改写数据根里的文件。

    两件事分开是有意的：回显一份没人读的键＝假装这条词汇还活着；而一次 GET 顺手
    "清理"别人的盘＝把读操作变成一次不可逆的写（判据
    `testReadingTheFileDoesNotRewriteIt` 钉这条边界）。
    """
    cleaned = {k: v for k, v in settings.items() if k != RETIRED_LANGUAGE_KEY}
    general = cleaned.get("general")
    if isinstance(general, dict) and RETIRED_LANGUAGE_KEY in general:
        cleaned["general"] = {k: v for k, v in general.items()
                              if k != RETIRED_LANGUAGE_KEY}
    return cleaned


# CORS 的名单、方法、头、配置落点与三级优先都在 `neurova.api.cors_policy` 一处。
# 本模块此前自持一份 8 项 origins 白名单（与 api/middleware 那份逐字重复）、
# 两份 methods/headers 清单，且 GET 不看 env——面板显示的与实际生效的不是同一份。
def _corsConfigFile() -> FilePath:
    """CORS 配置落点。conftest 与判据重定向的是 `cors_policy.configFile` 这一个接缝。"""
    return cors_policy.configFile()


class SettingsResponse(BaseModel):
    """设置响应"""

    settings: Dict[str, Any]
    updated_at: Optional[str] = None


class UpdateSettingsRequest(BaseModel):
    """更新设置请求"""

    settings: Dict[str, Any] = Field(..., description="设置键值对")


class SshCredentialRequest(BaseModel):
    """SSH 主机凭据（多主机按 host 分键；密钥/密码加密落盘，读取永不回显）"""

    host: str = Field(..., description="目标主机 IP/域名（作为分键）")
    user: str = Field("", description="SSH 用户名")
    port: int = Field(22, ge=1, le=65535, description="SSH 端口")
    key_text: str = Field("", description="私钥文本（粘贴，与 password 二选一，优先）")
    password: str = Field("", description="密码（无密钥时用）")


class SocialCredentialRequest(BaseModel):
    """社交平台凭据（web_reach social_exec 消费；键由该平台所需集决定）"""

    platform: str = Field(..., description="平台：twitter/reddit/xiaohongshu/facebook/instagram/linkedin/github")
    credentials: Dict[str, str] = Field(default_factory=dict, description="凭据键值（仅接受该平台所需键）")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _merged_settings() -> Dict[str, Any]:
    """设置统一读源（2026-09-12 P7）：进程内默认 + 持久化 flat 段 + 结构化 section。

    原缺陷：flat 键（theme/language/auto_save/...）PUT 只写内存 `_default_settings`
    谎报保存且重启丢；单键 GET 只读内存与整表 GET（已合并持久层）语义分裂。
    flat 键现统一落 data/app_settings.json 的 "flat" section。
    """
    from neurova.core.app_settings import load_app_settings

    stored = load_app_settings()
    flat = stored.pop("flat", None) or {}
    settings = dict(_default_settings)
    settings.update(flat)
    settings.update(stored)
    return _dropRetiredLanguageKeys(settings)


@router.get("", response_model=SettingsResponse)
async def get_settings(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取全局设置 — 登录用户可读（结构化 section 持久化 + 平铺 legacy 键）"""
    _get_request_id(request)

    return SettingsResponse(
        settings=_merged_settings(),
        updated_at=str(time.time()),
    )


def _hot_apply_output_budget(request: Request) -> int:
    """把全局默认输出预算热应用到存活 agent（仅补默认/跟进自己应用过的值，
    用户显式配置永不覆盖）。失败静默——预算在 agent 重建时仍会应用。"""
    applied = 0
    try:
        agents = getattr(getattr(request.app, "state", None), "agents", None) or {}
        from neurova.core.app_settings import apply_global_output_budget

        for agent in agents.values():
            config = getattr(getattr(agent, "llm_client", None), "config", None)
            if config is not None and apply_global_output_budget(config):
                applied += 1
    except Exception:  # noqa: BLE001
        logger.debug("输出预算热应用失败（跳过）", exc_info=True)
    return applied


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: Request,
    body: UpdateSettingsRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新全局设置（仅管理员）— section 值为 dict 时持久化到 app_settings"""
    _get_request_id(request)

    from neurova.core.app_settings import save_app_settings

    # 先整批校验再落盘：边校验边写会得到"第 2 项被拒、第 1 项已经写进去了"——
    # 报错与状态变更不一致，调用方重试时面对的是一个自己没打算要过的中间态。
    if RETIRED_LANGUAGE_KEY in body.settings:
        _rejectRetiredLanguageKey(RETIRED_LANGUAGE_KEY, "PUT /v1/settings 的平铺键")
    for key, value in body.settings.items():
        if key in _SETTINGS_SECTIONS and isinstance(value, dict):
            if RETIRED_LANGUAGE_KEY in value:
                _rejectRetiredLanguageKey(RETIRED_LANGUAGE_KEY, f"`{key}` section")

    flat_updates: Dict[str, Any] = {}
    for key, value in body.settings.items():
        if key in _SETTINGS_SECTIONS and isinstance(value, dict):
            save_app_settings(key, value)
        else:
            flat_updates[key] = value
    if flat_updates:
        # P7：flat 键落盘（原只写内存谎报保存）；同步进程内默认保持读一致
        save_app_settings("flat", flat_updates)
        _default_settings.update(flat_updates)

    if "advanced" in body.settings:
        applied = _hot_apply_output_budget(request)
        if applied:
            logger.info("全局输出预算已热应用到 %d 个存活 agent", applied)

    return SettingsResponse(
        settings=_merged_settings(),
        updated_at=str(time.time()),
    )


# ─── SSH 多主机凭据（computer_ssh_exec 消费；按当前用户分桶，登录即可自管）───


@router.get("/ssh-credentials")
async def list_ssh_credentials(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出当前用户已配置的 SSH 主机（脱敏：host/user/port/auth，不回显密钥/密码）。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    return {"code": 0, "data": {"hosts": get_credential_store().list_ssh_hosts(uid)}}


@router.post("/ssh-credentials")
async def upsert_ssh_credential(
    request: Request,
    body: SshCredentialRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """新增/更新一个 SSH 主机凭据（加密落盘）。host 必填；key_text 与 password 至少其一。"""
    host = (body.host or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="host 不能为空")
    if not body.key_text and not body.password:
        raise HTTPException(status_code=422, detail="需提供 key_text（私钥）或 password 之一")
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    ok = get_credential_store().set_ssh_host(
        uid, host, user=body.user, port=body.port, key_text=body.key_text, password=body.password
    )
    if not ok:
        raise HTTPException(status_code=500, detail="SSH 凭据保存失败")
    return {"code": 0, "data": {"host": host, "saved": True}}


@router.delete("/ssh-credentials/{host}")
async def delete_ssh_credential(
    request: Request,
    host: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除一个 SSH 主机凭据。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    if not get_credential_store().delete_ssh_host(uid, host):
        raise HTTPException(status_code=404, detail=f"未找到主机凭据: {host}")
    return {"code": 0, "data": {"host": host, "deleted": True}}


# ─── 社交平台凭据（web_reach social_exec 消费；与 SSH 复用同一配置面/加密桶）───


@router.get("/social-credentials")
async def list_social_credentials(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出各社交平台凭据配置状态（脱敏：平台 + 所需键是否已配，不回显值）。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    return {"code": 0, "data": {"platforms": get_credential_store().platform_status(uid)}}


@router.post("/social-credentials")
async def set_social_credential(
    request: Request,
    body: SocialCredentialRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """保存某社交平台凭据（只接受该平台所需键；空值不覆盖）。"""
    from neurova.web_reach.credentials import PLATFORM_REQUIRED_KEYS, get_credential_store

    platform = (body.platform or "").strip().lower()
    if platform not in PLATFORM_REQUIRED_KEYS:
        raise HTTPException(status_code=422, detail=f"不支持的平台: {body.platform}")
    if not any((body.credentials or {}).values()):
        raise HTTPException(status_code=422, detail="未提供任何凭据值")
    uid = str(current_user.get("user_id") or "default")
    ok = get_credential_store().set_platform_credentials(uid, platform, body.credentials)
    if not ok:
        raise HTTPException(status_code=500, detail="凭据保存失败")
    return {"code": 0, "data": {"platform": platform, "saved": True}}


@router.delete("/social-credentials/{platform}")
async def clear_social_credential(
    request: Request,
    platform: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """清除某社交平台的全部凭据。"""
    from neurova.web_reach.credentials import PLATFORM_REQUIRED_KEYS, get_credential_store

    platform = (platform or "").strip().lower()
    if platform not in PLATFORM_REQUIRED_KEYS:
        raise HTTPException(status_code=404, detail=f"不支持的平台: {platform}")
    uid = str(current_user.get("user_id") or "default")
    n = get_credential_store().clear_platform_credentials(uid, platform)
    return {"code": 0, "data": {"platform": platform, "cleared": n}}


# ─── CORS 配置管理（必须在 /{key} 之前注册，避免被路径参数遮蔽）───


class CorsConfigResponse(BaseModel):
    """CORS 配置响应"""

    origins: List[str]
    allow_credentials: bool = True
    allow_methods: List[str] = list(cors_policy.ALLOW_METHODS)
    allow_headers: List[str] = list(cors_policy.ALLOW_HEADERS)
    updated_at: Optional[str] = None


class UpdateCorsConfigRequest(BaseModel):
    """更新 CORS 配置请求"""

    origins: List[str] = Field(..., description="允许的来源列表")
    allow_credentials: Optional[bool] = Field(None, description="是否允许凭证")
    allow_methods: Optional[List[str]] = Field(None, description="允许的 HTTP 方法")
    allow_headers: Optional[List[str]] = Field(None, description="允许的请求头")


def _load_cors_config(config_file=None) -> Dict[str, Any]:
    """当前**实际生效**的 CORS 配置——委托单源，与中间件共读同一份。

    此前这里只看文件、不看 `NEUROVA_CORS_ORIGINS`，而中间件看的正是 env：
    设了 env 之后面板显示的是一份**没在生效**的清单，管理员照着改就改错了东西。
    """
    return cors_policy.effectiveConfig(config_file)


def _save_cors_config(config: Dict[str, Any]) -> bool:
    """保存 CORS 配置到文件"""
    try:
        target = _corsConfigFile()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("Failed to save CORS config: %s", e)
        return False


@router.get("/cors", response_model=CorsConfigResponse)
async def get_cors_config(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取 CORS 配置 — 登录用户可读"""
    _get_request_id(request)
    config = _load_cors_config()

    return CorsConfigResponse(
        origins=config["origins"],
        allow_credentials=config["allow_credentials"],
        allow_methods=config["allow_methods"],
        allow_headers=config["allow_headers"],
        updated_at=str(time.time()),
    )


@router.put("/cors", response_model=CorsConfigResponse)
async def update_cors_config(
    request: Request,
    body: UpdateCorsConfigRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新 CORS 配置（仅管理员；未授权篡改 CORS 白名单可绕过浏览器同源保护）"""
    _get_request_id(request)

    # 验证 origins 格式
    validated_origins = []
    for origin in body.origins:
        origin = origin.strip()
        if not origin:
            continue
        # 验证 URL 格式
        if not origin.startswith("http://") and not origin.startswith("https://"):
            raise HTTPException(
                status_code=400, detail=f"Invalid origin format: {origin}. Must start with http:// or https://"
            )
        validated_origins.append(origin)

    if not validated_origins:
        raise HTTPException(status_code=400, detail="At least one origin is required")

    config = _load_cors_config()
    config["origins"] = validated_origins

    if body.allow_credentials is not None:
        config["allow_credentials"] = body.allow_credentials
    if body.allow_methods is not None:
        config["allow_methods"] = body.allow_methods
    if body.allow_headers is not None:
        config["allow_headers"] = body.allow_headers

    if not _save_cors_config(config):
        raise HTTPException(status_code=500, detail="Failed to save CORS config")

    logger.info("CORS config updated by user, origins: %s", validated_origins)

    # 回显再从单源读一次：写进文件 ≠ 就是生效值（env 可能压着它，中间件也只在启动时读一次）。
    # 报「重启后实际会生效的那份」，不报「你刚提交的那份」——后者会让 PUT 成功回执与 GET 不一致。
    effective = _load_cors_config()
    return CorsConfigResponse(
        origins=effective["origins"],
        allow_credentials=effective["allow_credentials"],
        allow_methods=effective["allow_methods"],
        allow_headers=effective["allow_headers"],
        updated_at=str(time.time()),
    )


@router.post("/clear-cache")
async def clear_cache(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """清空已注册的内存缓存（存储设置页的「清缓存」入口）。

    此前前端 `settings.clearCache` 发 `POST /api/v1/settings/clear-cache`，
    本文件从未注册过该路由 —— 实测 405，按钮点下去必报错。
    缓存侧能力早已存在：注册表持有全部 `MemoryCache` 实例（此前只被 `/metrics` 读取）。
    这里给它接上写消费者，让「清缓存」作用在真实对象上，而不是造一个恒真的空转端点。

    取数走 `clearRegisteredCaches()` 一个公开口：注册表是缓存模块的私有状态，
    端点直接读 `_cache_registry` 等于在实装外面又写一条读取路径。
    """
    from neurova.core.cache import clearRegisteredCaches

    cleared: Dict[str, int] = clearRegisteredCaches()
    return {
        "code": 0,
        "message": "缓存已刷新",
        "data": {"caches": cleared, "total_cleared": sum(cleared.values())},
        "request_id": _get_request_id(request),
    }


# ─── 单个设置（/{key} 必须放在 /cors 之后）───


@router.get("/{key}")
async def get_setting(
    request: Request,
    key: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取特定设置 — 登录用户可读（读源与整表一致：默认+持久化）"""
    _get_request_id(request)

    settings = _merged_settings()
    if key not in settings:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return {
        "code": 0,
        "data": {
            "key": key,
            "value": settings[key],
        },
    }


@router.put("/{key}")
async def update_setting(
    request: Request,
    key: str = Path(...),
    value: Any = Body(..., embed=True),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新特定设置（仅管理员）— 落 app_settings 的 flat 段（P7：原只写内存谎报保存）"""
    _get_request_id(request)

    from neurova.core.app_settings import save_app_settings

    if key in _SETTINGS_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'{key}' 是结构化 section，请用 PUT /v1/settings 提交对象",
        )
    # 同根因的第二个写口（教义第 5 条）：整表 PUT 拒了而单键不拒，旧键就能从这里活回来
    _rejectRetiredLanguageKey(key, f"PUT /v1/settings/{key}")
    save_app_settings("flat", {key: value})
    _default_settings[key] = value

    return {
        "code": 0,
        "message": f"Setting '{key}' updated",
        "data": {
            "key": key,
            "value": value,
        },
    }
