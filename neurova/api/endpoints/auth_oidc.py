from __future__ import annotations

"""
通用 OIDC SSO 端点（S7）

链路：
1. GET /api/v1/auth/oidc/authorize  → 302 到 IdP 的 authorize 端点（带 state+nonce，
   state 落 users.db 的 oidc_states 表（多 worker 共享）：TTL 10 分钟、一次性消费）
2. IdP 认证后回跳 GET /api/v1/auth/oidc/callback?code&state
   → 用 code 换 token → 校验 id_token → 按 sub 供应用户 → 签发本仓 JWT 对
3. GET /api/v1/auth/oidc/status     → 公开暴露 {enabled}，前端据此决定是否显示 SSO 按钮

配置（环境变量，任一缺失即未启用；authorize/callback 诚实 503）：
- NEUROVA_OIDC_ISSUER        IdP 签发者根 URL（如 https://idp.example.com/realms/main）
- NEUROVA_OIDC_CLIENT_ID     客户端标识
- NEUROVA_OIDC_CLIENT_SECRET 客户端密钥
- NEUROVA_OIDC_SCOPES        默认 "openid profile email"
- NEUROVA_OIDC_REDIRECT_URI  可选；缺省按请求基址拼 callback（反代/域名固定时建议显式配置）

id_token 校验选型：**PyJWT，按 id_token header.alg 分派验签材料**。HS256 用
client_secret 验签（confidential client 的 client_secret 后通道，id_token 由后端
直连 IdP token 端点（TLS）取回，不经过浏览器）；RS256/ES256 走 discovery 文档的
jwks_uri 公钥集合按 kid 匹配（缓存纪律同 discovery）。PyJWT 的非对称算法依赖
cryptography，缺失时该分支 401 诚实报因，不裸崩。header.alg 只用来选材料，
decode 的 algorithms 白名单与所选材料一一对应，不制造 alg 混淆面。

用户供应规则：按 oidc_sub 找人 → 无则按**已验证** email（id_token 的
email_verified=true）绑定现有号（回写 oidc_sub）→ 再无则建号（role 由
UserModel.createUserWithBootstrapRole 在写入事务内判定："系统无用户时首个
账号即管理员"，与 endpoints/auth.py register 同一单源）。停用账号（status
!= active）不绑定、不发令牌。
"""

import hashlib
import json
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from neurova.core import config
from neurova.core.db_migration import apply_domain_steps, register_migration
from neurova.core.database import get_short_connection, release_short_connection
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# ── 配置读取 ───────────────────────────────────────────────────────────────
# 进程环境变量优先，回落 config（.env 已在启动期并入进程环境；两处同源，
# 这里不造第二份配置事实源，只是保证测试 monkeypatch.setenv 即时生效）。

_OIDC_ISSUER_ENV = "NEUROVA_OIDC_ISSUER"
_OIDC_CLIENT_ID_ENV = "NEUROVA_OIDC_CLIENT_ID"
_OIDC_CLIENT_SECRET_ENV = "NEUROVA_OIDC_CLIENT_SECRET"
_OIDC_SCOPES_ENV = "NEUROVA_OIDC_SCOPES"
_OIDC_REDIRECT_URI_ENV = "NEUROVA_OIDC_REDIRECT_URI"

DEFAULT_SCOPES = "openid profile email"

#: 发现文档缓存 TTL；id_token 时钟容差交给 PyJWT 的 exp/iat 校验 + leeway
_DISCOVERY_TTL_SECONDS = 3600
#: authorize state 短时存储 TTL（一次性，超时即拒）
_STATE_TTL_SECONDS = 600


def _setting(name: str) -> str:
    import os

    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    try:
        return str(config.get(name) or "").strip()
    except Exception:  # noqa: BLE001 - config 未初始化时按缺省处理
        return ""


def _oidcConfig() -> Optional[Dict[str, str]]:
    """读取 OIDC 三要素；任一缺失返回 None（调用方诚实报缺）。"""
    issuer = _setting(_OIDC_ISSUER_ENV)
    client_id = _setting(_OIDC_CLIENT_ID_ENV)
    client_secret = _setting(_OIDC_CLIENT_SECRET_ENV)
    if not (issuer and client_id and client_secret):
        return None
    return {
        "issuer": issuer.rstrip("/"),
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": _setting(_OIDC_SCOPES_ENV) or DEFAULT_SCOPES,
        "redirect_uri": _setting(_OIDC_REDIRECT_URI_ENV),
    }


def _missingConfigNames() -> list:
    names = []
    if not _setting(_OIDC_ISSUER_ENV):
        names.append(_OIDC_ISSUER_ENV)
    if not _setting(_OIDC_CLIENT_ID_ENV):
        names.append(_OIDC_CLIENT_ID_ENV)
    if not _setting(_OIDC_CLIENT_SECRET_ENV):
        names.append(_OIDC_CLIENT_SECRET_ENV)
    return names


# ── IdP 发现文档（{issuer}/.well-known/openid-configuration）───────────────
# issuer 是运维配置的基础设施地址（部署方在环境变量里指定的可信 IdP），
# 按 S2 分类豁免 url_guard 的公网校验——它不是用户可控输入，而是与数据库、
# SMTP 同级的部署期可信配置； url_guard 管的是"把用户/租户输入当 URL 用"的面。

_discoveryCache: Dict[str, Tuple[Dict[str, Any], float]] = {}
_discoveryLock = threading.RLock()


def _fetchDiscovery(issuer: str) -> Dict[str, Any]:
    now = time.time()
    with _discoveryLock:
        cached = _discoveryCache.get(issuer)
        if cached and now - cached[1] < _DISCOVERY_TTL_SECONDS:
            return cached[0]
    url = f"{issuer}/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        doc = resp.json()
    if not doc.get("token_endpoint"):
        raise ValueError("IdP 发现文档缺少 token_endpoint")
    with _discoveryLock:
        _discoveryCache[issuer] = (doc, now)
    return doc


# ── IdP JWKS（非对称验签公钥集合，缓存纪律同 discovery）────────────────────

_jwksCache: Dict[str, Tuple[list, float]] = {}
_jwksLock = threading.RLock()


def _fetchJwks(oidcConfig: Dict[str, str]) -> list:
    """从 discovery.jwks_uri 拉取公钥集合；按 URI 缓存、TTL 同 discovery。"""
    discovery = _fetchDiscovery(oidcConfig["issuer"])
    jwksUri = str(discovery.get("jwks_uri") or "").strip()
    if not jwksUri:
        raise HTTPException(status_code=401,
                            detail="OIDC 发现文档缺少 jwks_uri，无法验签非对称 id_token")
    now = time.time()
    with _jwksLock:
        cached = _jwksCache.get(jwksUri)
        if cached and now - cached[1] < _DISCOVERY_TTL_SECONDS:
            return cached[0]
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(jwksUri)
            resp.raise_for_status()
            keys = resp.json().get("keys") or []
    except httpx.HTTPError as e:
        logger.warning("OIDC JWKS 拉取失败 uri=%s: %s", jwksUri, e)
        raise HTTPException(status_code=502, detail="OIDC JWKS 端点不可达")
    with _jwksLock:
        _jwksCache[jwksUri] = (keys, now)
    return keys


# ── authorize state 短时存储（users.db oidc_states 表、TTL、一次性）─────────
# 多 worker/多进程部署下 authorize 与 callback 可能落到不同进程，state 必须出进程；
# 与用户账本同库（users.db），schema 走 db_migration 注册表 domain=auth_oidc v2
# （v1 = users.oidc_sub，登记在 neurova/auth/user_model.py）。

#: v2：oidc_states 表。state 只存 sha256 摘要（库被拖走也还原不出可用 state），
#: nonce 存原文（id_token 校验要用），created_at REAL 供 TTL 判定。
_STATE_SCHEMA_VERSION = 2


def _migrateOidcStatesTable(conn) -> None:
    """v2：建 oidc_states 表 + created_at 索引（幂等；TTL 清理走该列）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS oidc_states (
            state_hash TEXT PRIMARY KEY,
            nonce TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_oidc_states_created_at ON oidc_states(created_at)"
    )


_stateSchemaReadyPaths: set = set()
_stateSchemaLock = threading.RLock()
_stateDbLock = threading.RLock()


def _stateDbPath() -> str:
    """state 表所在库 = 用户账本库（users.db）；路径以 UserModel 为单一事实源。"""
    from neurova.api.endpoints.auth import _get_user_model

    return _get_user_model().db_path


def _ensureStateSchema() -> str:
    """确保 oidc_states 表已建，返回 users.db 路径（DCL 懒初始化）。

    v2 走懒注册：auth_oidc 域的 v1 在 user_model.py 模块级登记，若本模块在
    import 期直接登记 v2，导入顺序颠倒会让 v1 登记撞"版本必须严格递增"——
    故首次使用时先 import user_model（v1 随之入表）再幂等登记 v2、幂等应用。
    """
    dbPath = _stateDbPath()
    if dbPath in _stateSchemaReadyPaths:
        return dbPath
    with _stateSchemaLock:
        if dbPath in _stateSchemaReadyPaths:
            return dbPath
        from neurova.auth import user_model as userModelModule

        register_migration(_STATE_SCHEMA_VERSION, _migrateOidcStatesTable,
                           domain=userModelModule.USERS_OIDC_DOMAIN)
        conn = get_short_connection(dbPath)
        try:
            apply_domain_steps(conn, userModelModule.USERS_OIDC_DOMAIN)
        finally:
            release_short_connection(conn)
        _stateSchemaReadyPaths.add(dbPath)
    return dbPath


def _hashState(state: str) -> str:
    """state 只以 sha256 摘要落库；落库后按摘要等值查询，无时序侧信道面。"""
    return hashlib.sha256((state or "").encode("utf-8")).hexdigest()


def _storeState(state: str, nonce: str) -> None:
    """state 落 users.db（多 worker 共享）；写入时顺带清理过期行。"""
    now = time.time()
    dbPath = _ensureStateSchema()
    with _stateDbLock:
        conn = get_short_connection(dbPath)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM oidc_states WHERE created_at < ?",
                         (now - _STATE_TTL_SECONDS,))
            conn.execute(
                "INSERT OR REPLACE INTO oidc_states (state_hash, nonce, created_at) "
                "VALUES (?, ?, ?)",
                (_hashState(state), nonce, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            release_short_connection(conn)


def _consumeState(state: str) -> Optional[str]:
    """取走 state（一次性）；不存在或已过期返回 None。

    BEGIN IMMEDIATE 串行化同库写者：两个 worker 同时消费同一 state 时，后到者
    进事务后行已被删 → None，一次性语义跨进程成立。过期行同样删除（顺手清账）。
    """
    dbPath = _ensureStateSchema()
    stateHash = _hashState(state)
    now = time.time()
    with _stateDbLock:
        conn = get_short_connection(dbPath)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT nonce, created_at FROM oidc_states WHERE state_hash = ?",
                (stateHash,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            conn.execute("DELETE FROM oidc_states WHERE state_hash = ?", (stateHash,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            release_short_connection(conn)
    if now - row["created_at"] > _STATE_TTL_SECONDS:
        return None
    return row["nonce"]


# ── 用户供应（按 sub → email → 建号）──────────────────────────────────────

def _uniqueUsername(model, base: str) -> str:
    candidate = base
    suffix = 0
    while model.get_user_by_username(candidate) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def _provisionOidcUser(model, sub: str, email: str, preferred_username: str,
                       email_verified: bool = False):
    """按 oidc_sub → 已验证 email 绑定 → 建号 的供应规则返回既有/新建 User。

    API-04（审计 2026-11-25）：
    - email 绑定只接受 **IdP 已验证** 的邮箱（email_verified=true）。信任
      "不验证邮箱的 IdP" 时，任何人把 IdP 资料邮箱填成他人邮箱即可绑定他人
      账号——未验证邮箱一律不绑定、也不落库（users 表无 verified 标记列，
      存了即被下游当真）。
    - 命中的既有账号 status != active 时拒绝绑定（不把 sub 绑到停用账号上）。
    - 首管理员判定走 createUserWithBootstrapRole 事务内单源（并发首登不产生
      双管理员）。
    """
    existing = model.get_user_by_oidc_sub(sub)
    if existing is not None:
        return existing

    verifiedEmail = email if (email and email_verified) else None
    if verifiedEmail:
        byEmail = model.get_user_by_email(verifiedEmail)
        if byEmail is not None:
            if byEmail.status != "active":
                raise HTTPException(status_code=403, detail="Account is inactive")
            # 绑定现有号：IdP 已验证该邮箱归属，回写 sub 形成绑定
            model.update_user(byEmail.id, oidc_sub=sub)
            return model.get_user_by_id(byEmail.id)

    # 建号：用户名取邮箱前缀或 sub 派生；口令置为不可用的随机哈希（SSO 账号
    # 不经密码登录，但 password_hash 列 NOT NULL）；首用户即管理员——判定与
    # 写入原子化（createUserWithBootstrapRole，与 register 的 is_bootstrap
    # 口径同一事务内单源）。
    base = (email.split("@")[0] if email else "") or f"oidc-{sub[:12]}"
    safeBase = "".join(ch for ch in base if ch.isalnum() or ch in "._-") or f"oidc-{sub[:12]}"
    from neurova.api.auth import hash_password

    return model.createUserWithBootstrapRole(
        username=_uniqueUsername(model, safeBase),
        password_hash=hash_password(secrets.token_urlsafe(32)),
        email=verifiedEmail or None,
        oidc_sub=sub,
    )


# ── id_token 校验（header.alg 分派：HS256=client_secret；RS256/ES256=JWKS）──

def _publicKeyFromJwk(jwk: Dict[str, Any], alg: str):
    """JWK → 验签公钥。PyJWT 的非对称算法需要 cryptography，缺失时抛
    MissingCryptographyError（调用方统一转 401 诚实报因）。"""
    from jwt.algorithms import ECAlgorithm, RSAAlgorithm

    kty = str(jwk.get("kty") or "")
    if alg == "RS256" and kty == "RSA":
        return RSAAlgorithm.from_jwk(json.dumps(jwk))
    if alg == "ES256" and kty == "EC":
        return ECAlgorithm.from_jwk(json.dumps(jwk))
    raise ValueError(f"JWKS 公钥与算法不匹配: alg={alg} kty={kty}")


def _jwksSigningKey(oidcConfig: Dict[str, str], header: Dict[str, Any]):
    """按 header.kid 从 JWKS 选公钥；无 kid / kid 不匹配 / 依赖缺失 → 401 诚实。"""
    import hmac as _hmac

    kid = str(header.get("kid") or "")
    if not kid:
        raise HTTPException(status_code=401,
                            detail="OIDC id_token 缺少 kid，无法匹配 JWKS 公钥")
    alg = str(header.get("alg") or "")
    keys = _fetchJwks(oidcConfig)
    for jwk in keys:
        if _hmac.compare_digest(str(jwk.get("kid") or ""), kid):
            try:
                return _publicKeyFromJwk(jwk, alg)
            except (jwt.exceptions.MissingCryptographyError, ImportError):
                raise HTTPException(
                    status_code=401,
                    detail="OIDC 非对称验签（RS256/ES256）需安装 cryptography 依赖",
                )
            except Exception as e:  # noqa: BLE001 - 公钥构建失败按验签失败处理
                logger.warning("OIDC JWKS 公钥构建失败 kid=%s: %s", kid, e)
                raise HTTPException(status_code=401, detail="OIDC id_token 验签公钥不可用")
    raise HTTPException(status_code=401, detail="OIDC id_token kid 与 JWKS 公钥不匹配")


def _verifyIdToken(idToken: str, oidcConfig: Dict[str, str], expectedNonce: str) -> Dict[str, Any]:
    """验签 + iss/aud/exp + nonce；任一不符抛 HTTPException(401)。

    header.alg 只用来选验签材料：HS256 → client_secret；RS256/ES256 → JWKS
    公钥（kid 匹配）。decode 的 algorithms 白名单与材料一一对应，不接受
    其它算法（含 none）。
    """
    import hmac as _hmac

    try:
        header = jwt.get_unverified_header(idToken)
    except jwt.PyJWTError as e:
        logger.warning("OIDC id_token header 解析失败: %s", e)
        raise HTTPException(status_code=401, detail="OIDC id_token 校验失败")

    alg = str(header.get("alg") or "")
    decodeKwargs = dict(audience=oidcConfig["client_id"], issuer=oidcConfig["issuer"])
    try:
        if alg == "HS256":
            claims = jwt.decode(idToken, oidcConfig["client_secret"],
                                algorithms=["HS256"], **decodeKwargs)
        elif alg in ("RS256", "ES256"):
            key = _jwksSigningKey(oidcConfig, header)
            claims = jwt.decode(idToken, key, algorithms=[alg], **decodeKwargs)
        else:
            raise HTTPException(status_code=401,
                                detail=f"OIDC id_token 签名算法不受支持: {alg or '缺失'}")
    except jwt.exceptions.MissingCryptographyError:
        raise HTTPException(status_code=401,
                            detail="OIDC 非对称验签（RS256/ES256）需安装 cryptography 依赖")
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        logger.warning("OIDC id_token 校验失败: %s", e)
        raise HTTPException(status_code=401, detail="OIDC id_token 校验失败")

    nonce = str(claims.get("nonce") or "")
    if not nonce or not _hmac.compare_digest(nonce, expectedNonce or ""):
        raise HTTPException(status_code=401, detail="OIDC nonce 校验失败")
    return claims


def _auditOidcLogin(user_id: Optional[str], request: Request, success: bool, sub: str = "") -> None:
    """SSO 登录成败入审计（复用 endpoints/auth 的 AUTH_LOGIN/AUTH_FAILED 单源）。"""
    try:
        from neurova.api.endpoints.auth import _auditAuthLogin

        _auditAuthLogin(user_id, request, success=success, attempted_username=sub)
    except Exception as e:  # noqa: BLE001 - 审计失败不阻断 SSO 主流程
        logger.warning("OIDC 审计写入失败: %s", e)


# ── 端点 ──────────────────────────────────────────────────────────────────

@router.get("/status")
async def oidcStatus():
    """SSO 可用性（公开）：前端登录页据此决定是否渲染 SSO 按钮。"""
    return {"enabled": _oidcConfig() is not None}


@router.get("/authorize")
async def oidcAuthorize(request: Request):
    """302 到 IdP authorize 端点；state+nonce 由本仓生成并短时保存。"""
    oidcConfig = _oidcConfig()
    if oidcConfig is None:
        missing = ", ".join(_missingConfigNames())
        raise HTTPException(status_code=503, detail=f"OIDC SSO 未配置：缺少 {missing}")

    try:
        discovery = _fetchDiscovery(oidcConfig["issuer"])
    except Exception as e:  # noqa: BLE001 - 发现文档不可达是上游故障，诚实上报
        logger.error("OIDC 发现文档获取失败 issuer=%s: %s", oidcConfig["issuer"], e)
        raise HTTPException(status_code=503, detail="OIDC IdP 不可达（发现文档获取失败）")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    _storeState(state, nonce)

    redirectUri = oidcConfig["redirect_uri"] or str(request.base_url).rstrip("/") + "/api/v1/auth/oidc/callback"
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": oidcConfig["client_id"],
        "redirect_uri": redirectUri,
        "scope": oidcConfig["scopes"],
        "state": state,
        "nonce": nonce,
    }
    return RedirectResponse(
        discovery["authorization_endpoint"] + "?" + urlencode(params),
        status_code=302,
    )


@router.get("/callback")
async def oidcCallback(request: Request, code: str = "", state: str = ""):
    """code 换 token → 校验 id_token → 供应用户 → 签发本仓 JWT 对。"""
    oidcConfig = _oidcConfig()
    if oidcConfig is None:
        missing = ", ".join(_missingConfigNames())
        raise HTTPException(status_code=503, detail=f"OIDC SSO 未配置：缺少 {missing}")

    nonce = _consumeState(state)
    if nonce is None:
        raise HTTPException(status_code=400, detail="OIDC state 无效或已过期")
    if not code:
        raise HTTPException(status_code=400, detail="OIDC callback 缺少 code")

    discovery = _fetchDiscovery(oidcConfig["issuer"])
    tokenEndpoint = discovery["token_endpoint"]
    redirectUri = oidcConfig["redirect_uri"] or str(request.base_url).rstrip("/") + "/api/v1/auth/oidc/callback"

    # code 换 token： confidential client 走 client_secret 后通道
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tokenResp = await client.post(
                tokenEndpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirectUri,
                    "client_id": oidcConfig["client_id"],
                    "client_secret": oidcConfig["client_secret"],
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as e:
        logger.error("OIDC token 端点请求失败: %s", e)
        raise HTTPException(status_code=502, detail="OIDC token 端点不可达")
    if tokenResp.status_code != 200:
        logger.warning("OIDC token 交换失败: status=%s body=%s", tokenResp.status_code, tokenResp.text[:200])
        raise HTTPException(status_code=502, detail="OIDC 授权码交换失败")
    tokenPayload = tokenResp.json()
    idToken = tokenPayload.get("id_token")
    if not idToken:
        raise HTTPException(status_code=502, detail="OIDC token 响应缺少 id_token")

    claims = _verifyIdToken(idToken, oidcConfig, nonce)

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise HTTPException(status_code=401, detail="OIDC id_token 缺少 sub")
    email = str(claims.get("email") or "").strip()
    preferred = str(claims.get("preferred_username") or "").strip()
    # API-04：email_verified 标准 claim（布尔；个别 IdP 用字符串形态，兼容判真）
    rawVerified = claims.get("email_verified")
    emailVerified = rawVerified is True or str(rawVerified).strip().lower() in ("true", "1", "yes")

    # 供应用户（sub → 已验证 email 绑定 → 建号）
    from neurova.api.endpoints.auth import _get_user_model, buildIdentityClaims

    model = _get_user_model()
    user = _provisionOidcUser(model, sub=sub, email=email, preferred_username=preferred,
                              email_verified=emailVerified)
    if user is None:
        raise HTTPException(status_code=500, detail="OIDC 用户供应失败")

    # API-04：SSO 不得给停用账号发令牌（sub 命中复用的存量账号同样在此拦下）
    if user.status != "active":
        _auditOidcLogin(str(user.id), request, success=False, sub=sub)
        logger.warning("OIDC 登录拒绝：账号已停用 user_id=%s sub=%s", user.id, sub)
        raise HTTPException(status_code=403, detail="Account is inactive")

    from neurova.api.auth import create_access_token, create_refresh_token

    identityClaims = buildIdentityClaims({"id": user.id, "username": user.username})
    accessToken = create_access_token(data={**identityClaims, "role": user.role})
    refreshToken = create_refresh_token(data=identityClaims)

    try:
        model.log_login(
            user_id=user.id,
            username=user.username,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
    except Exception as e:  # noqa: BLE001 - 登录日志失败不阻断 SSO
        logger.warning("OIDC 登录日志写入失败: %s", e)
    _auditOidcLogin(str(user.id), request, success=True, sub=sub)

    return {
        "access_token": accessToken,
        "refresh_token": refreshToken,
        "token_type": "bearer",
        "expires_in": 3600,
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
    }
