from __future__ import annotations

"""
Neurova JWT 认证模块

功能:
1. JWT Token 生成 (Access Token + Refresh Token)
2. Token 验证
3. Token 刷新
4. 用户登录验证
"""

import datetime
from neurova.core import config
from neurova.core.logger import get_logger
import secrets
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = get_logger(__name__)

# JWT 配置
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)


class BearerOrQuery(HTTPBearer):
    """头凭证优先，无头时回退 `?access_token=`（批次 3：AIGC 产物资源标签场景）。

    原先住在 `api/deps.py`。它与 `get_current_user` 的两份并存实现一起收口到本模块，
    因为"凭证从哪儿来"与"身份怎么推导"必须同处一地才看得清放行面。
    """

    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:  # type: ignore[override]
        creds = await super().__call__(request)
        if creds:
            return creds
        token = request.query_params.get("access_token")
        if token:
            return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return None


securityWithQuery = BearerOrQuery(auto_error=False)


class AuthError(Exception):
    """认证错误"""

    def __init__(self, message: str, code: int = 401):
        self.message = message
        self.code = code
        super().__init__(message)


# 安全审计 M1: JWT 密钥最小长度（HS256 对称密钥，过短可被暴力破解）
_MIN_SECRET_LENGTH = 32

# .env.example 里的占位默认值，生产环境必须替换
_INSECURE_DEFAULT_SECRETS = {
    "your-secret-key-change-in-production",
    "changeme",
    "secret",
    "test",
}

_SECRET_FILENAME = ".jwt_secret"


def _secretFilePath() -> Path:
    """密钥文件落点：数据根下的 `.jwt_secret`（绝对路径）。

    原值 `Path(".jwt_secret")` 是 CWD 相对：换个启动目录就换个密钥文件，
    进程重启即视为"没有密钥"→ 重新生成 → 既有 token 全员失效。
    只在数据根无该文件时收养仓库根的旧文件，老部署不因此掉线。
    """
    from neurova.core.data_root import dataLanding

    return dataLanding(_SECRET_FILENAME)


def _is_production() -> bool:
    """是否生产环境（NEUROVA_ENV=production/prod，或显式关闭 debug）。"""
    import os

    env = (os.environ.get("NEUROVA_ENV") or config.get("NEUROVA_ENV") or "").strip().lower()
    if env in ("prod", "production"):
        return True
    # 未显式设 ENV 时，默认生产（fail-safe）；显式 NEUROVA_DEBUG=1 视为开发
    return os.environ.get("NEUROVA_DEBUG", "0") != "1"


def _validate_secret(secret: str) -> str:
    """校验密钥强度，弱密钥在生产环境直接拒绝启动（fail-closed）。"""
    if len(secret) < _MIN_SECRET_LENGTH:
        msg = (
            f"NEUROVA_JWT_SECRET 过短（{len(secret)} < {_MIN_SECRET_LENGTH} 字节），"
            "存在被暴力破解风险"
        )
        if _is_production():
            raise RuntimeError(msg + "；生产环境拒绝启动，请设置 ≥32 字节的强随机密钥")
        logger.warning(msg + "（开发环境放行）")
    if secret in _INSECURE_DEFAULT_SECRETS:
        msg = "检测到 .env.example 默认 JWT 密钥，必须替换"
        if _is_production():
            raise RuntimeError(msg + "；生产环境拒绝启动")
        logger.warning(msg + "（开发环境放行）")
    return secret


def _write_secret_file(secret: str) -> None:
    """写入 .jwt_secret，并收紧到 0600（仅属主可读，安全审计 M1）。"""
    import os

    try:
        _secretFilePath().write_text(secret)
        try:
            os.chmod(_secretFilePath(), 0o600)
        except OSError as e:  # 非 POSIX 或权限不足（如 Windows）降级为告警
            logger.warning("Failed to chmod .jwt_secret to 0600: %s", e)
    except Exception as e:
        logger.warning("Failed to save JWT secret: %s", e)


#: 自动生成密钥的**进程内唯一值**：一旦本进程确定，就不再因"谁在什么时候读它"而变。
#: 加锁的理由与全仓其余懒建单例同（AGENTS.md §3）：并发首取不加锁会各建一份。
_generatedSecretKey: Optional[str] = None
_generatedSecretLock = threading.RLock()


def _load_or_create_secret_key() -> str:
    """
    加载或创建持久化 JWT Secret Key

    优先级:
    1. 环境变量 NEUROVA_JWT_SECRET
    2. 配置文件 .jwt_secret
    3. 自动生成并保存（0600）

    安全审计 M1: 环境变量来源的密钥强制强度校验；文件来源自动收紧权限。
    """
    # 1. 环境变量（两个名字都收：`NEUROVA_JWT_SECRET` 是部署侧
    #    `deploy_config_consistency_check` 校验的那份；`NEUROVA_JWT_SECRET_KEY` 是全仓
    #    60 余处测试与诊断脚本的注入名 —— 只认前者的那些年里，后者一字不响地被忽略，
    #    于是"设了没生效"成了默认状态。两个名字都是密钥的**入口**，不是两份密钥。）
    env_key = config.get("NEUROVA_JWT_SECRET") or config.get("NEUROVA_JWT_SECRET_KEY")
    if env_key:
        return _validate_secret(env_key)

    # 2. 配置文件
    if _secretFilePath().exists():
        try:
            secret = _secretFilePath().read_text().strip()
            if secret:
                # 启动即收紧历史遗留文件的权限
                import os

                try:
                    if (os.stat(_secretFilePath()).st_mode & 0o077) != 0:
                        os.chmod(_secretFilePath(), 0o600)
                except OSError:
                    pass
                return _validate_secret(secret)
        except Exception:
            pass

    # 3. 自动生成
    #
    # **进程内只生成一次，落盘失败也不例外。** 此前每次都 `token_hex()` 现生成，而
    # 数据根不可写时（容器里目录还没就绪、只读挂载、权限不足）`_write_secret_file`
    # 只留一行 warning 就返回，调用方照旧拿到一枚**新**密钥——于是"谁在什么时候取过
    # 密钥"决定了他签出的 token 能不能被别处验过。实测（数据根不可写）：
    #
    #   同一进程连取三次 → 三个不同值；模块常量与任何一次重算都不相等。
    #
    # 这不是"多一枚缓存"，是同一件事只留一个答案（教义第 6 条）：落盘成功时下一进程
    # 从文件读回同一枚；落盘失败时本进程内保持稳定。跨重启换一枚是没有持久化的既定
    # 代价，但**同进程内签与验因此恒等**。
    global _generatedSecretKey
    with _generatedSecretLock:
        if _generatedSecretKey is None:
            _generatedSecretKey = secrets.token_hex(32)
            _write_secret_file(_generatedSecretKey)
        return _generatedSecretKey


def currentJwtSecretKey() -> str:
    """当前生效的签名/验签密钥 —— 取值口，幂等、不触发加载。

    存在的理由只有一个：让"这一轮用的是哪把密钥"有**一处**可问、可断言。判据侧此前
    各自抄一份常量（四份），台面上看不出谁的读法对；签名与验签又各读一处模块字典，
    一旦分叉就表现为"本档刚签的令牌被自己拒"（401 / `Signature verification failed`）。
    收成这一处之后，两边都从它取数。
    """
    return JWT_SECRET_KEY


# JWT Secret Key — 从环境变量或自动生成的文件加载
# 优先级: 环境变量 NEUROVA_JWT_SECRET / NEUROVA_JWT_SECRET_KEY > .jwt_secret 文件 > 自动生成
JWT_SECRET_KEY = _load_or_create_secret_key()


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    """
    创建 Access Token

    Args:
        data: Token 数据
        expires_delta: 过期时间增量

    Returns:
        JWT Token 字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "type": "access",
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "jti": str(uuid.uuid4()),
        }
    )

    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    """
    创建 Refresh Token

    Args:
        data: Token 数据
        expires_delta: 过期时间增量

    Returns:
        JWT Token 字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update(
        {
            "exp": expire,
            "type": "refresh",
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "jti": str(uuid.uuid4()),
        }
    )

    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_token_pair(
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    创建 Token 对 (Access + Refresh)

    Args:
        data: Token 数据

    Returns:
        包含 access_token 和 refresh_token 的字典
    """
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码 JWT Token

    Args:
        token: JWT Token 字符串

    Returns:
        Token 数据字典，失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", e)
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    验证 JWT Token

    Args:
        token: JWT Token 字符串
        token_type: Token 类型 ("access" 或 "refresh")

    Returns:
        Token 数据字典，失败返回 None
    """
    payload = decode_token(token)
    if not payload:
        return None

    # 检查 token 类型
    if payload.get("type") != token_type:
        logger.warning("Token type mismatch: expected %s, got %s", token_type, payload.get('type'))
        return None

    return payload


# ── 登出黑名单（全局单源；endpoints/auth.py logout 注册，verify 统一校验）──
_token_blacklist: Dict[str, float] = {}  # token -> 过期时间戳（用于清理）
_BLACKLIST_MAX = 20000


def blacklist_token(token: str, exp: float = 0.0) -> None:
    """登出时注册 token；超过容量上限时清理已过期条目防泄漏。"""
    import time as _time

    if len(_token_blacklist) >= _BLACKLIST_MAX:
        now = _time.time()
        for k in [k for k, v in _token_blacklist.items() if v and v <= now]:
            _token_blacklist.pop(k, None)
        if len(_token_blacklist) >= _BLACKLIST_MAX:
            _token_blacklist.clear()
    _token_blacklist[token] = exp


def is_token_blacklisted_global(token: str) -> bool:
    return token in _token_blacklist


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    if is_token_blacklisted_global(token):
        return None  # 已登出的 token 视为无效
    """验证 Access Token"""
    return verify_token(token, "access")


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 Refresh Token"""
    return verify_token(token, "refresh")


def get_token_subject(token: str) -> Optional[str]:
    """
    从 Token 中获取 subject (用户标识)

    Args:
        token: JWT Token 字符串

    Returns:
        用户标识，失败返回 None
    """
    payload = decode_token(token)
    if payload:
        return payload.get("sub")
    return None


def hash_password(password: str) -> str:
    """
    安全哈希密码

    优先使用 bcrypt，回退到 PBKDF2-SHA256（带随机盐）。
    绝不使用无盐哈希。

    Args:
        password: 明文密码

    Returns:
        哈希字符串（bcrypt 或 PBKDF2 格式）
    """
    try:
        import bcrypt

        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    except ImportError:
        # bcrypt 不可用时，使用 PBKDF2-SHA256（NIST 推荐的 KDF）
        import base64
        import hashlib

        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=260000)
        # 格式: pbkdf2:sha256:260000:<salt_b64>:<dk_b64>
        return f"pbkdf2:sha256:260000:{base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()}"


def verify_password(password: str, hashed: str) -> bool:
    """
    验证密码是否匹配哈希值

    Args:
        password: 明文密码
        hashed: 哈希值（bcrypt 或 PBKDF2-SHA256 格式）

    Returns:
        是否匹配

    安全说明:
        不再接受无盐 SHA-256 哈希（彩虹表攻击风险）。
        仅支持 bcrypt 和 PBKDF2-SHA256 两种带盐算法。
    """
    if not hashed:
        return False
    try:
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except ValueError:
            # 不是 bcrypt 哈希格式，继续尝试 PBKDF2
            pass
    except ImportError:
        pass

    # bcrypt 不可用或哈希不是 bcrypt 格式时，使用 PBKDF2-SHA256 验证
    import base64
    import hashlib

    if not hashed.startswith("pbkdf2:sha256:"):
        # 拒绝无盐 SHA-256 及任何未知格式（安全：不再回退到弱哈希）
        return False
    parts = hashed.split(":")
    if len(parts) != 5:
        return False
    _, _, iterations_b64, salt_b64, dk_b64 = parts
    salt = base64.b64decode(salt_b64)
    iterations = int(iterations_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=iterations)
    return base64.b64encode(dk).decode() == dk_b64


def _identityFromCredentialsOr401(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Dict[str, Any]:
    """凭证 → 身份字典（**唯一实现**）；缺失或无效一律显式 401。

    单一事实源的缘由：`api/deps.py` 曾有第二份同体逻辑（同名 `get_current_user`），
    两份对"有凭证但无效"的处置迟早漂移，且 override 打错对象时静默失效。
    `verify_access_token` 实测只 `return None` 从不抛（见 `verify_token`），
    所以这里不加 `except Exception` 兜底——加了就是"该显式失败却被吞"的形状。
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_identity(payload)


def _identityFromCredentialsOrNone(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[Dict[str, Any]]:
    """凭证 → 身份字典或 None（可选门的唯一实现）。

    与严格门的共同点是"坏凭证绝不换到身份"；差别只在**无凭证**：这里返回 None，
    而 `get_current_user_or_default` 返回共享的 default 租户。三者语义各不同，
    所以是三个入口共用两个推导函数，而不是三份推导。
    """
    if not credentials:
        return None
    payload = verify_access_token(credentials.credentials)
    if not payload:
        return None
    return _user_identity(payload)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI 依赖：获取当前认证用户（**只认 Authorization: Bearer**）

    Returns:
        用户信息字典

    Raises:
        HTTPException: 认证失败
    """
    return _identityFromCredentialsOr401(credentials)


async def get_current_userWithQueryToken(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(securityWithQuery),
) -> Dict[str, Any]:
    """同上，但凭证来源多一条：无头时回退 `?access_token=`。

    为什么不把它并成一份：`<img>`/`<audio>`/`<a download>` 等资源标签发不出
    Authorization 头，产物预览与下载只能走查询参数；但 token 进 URL 会落进访问日志
    与浏览器历史，所以放行面要**按端点显式选择**，不能因为"少写一个函数"就把它
    推广到全部 84 个用严格版的端点（那是放宽安全面）。
    名字必须与严格版不同——本仓曾有两份**同名不同体**的 get_current_user
    （auth 与 deps），结果 `dependency_overrides` 打到另一个对象上会静默失效，
    守卫"看起来没咬住"其实是替换没生效。判据见
    `tests/unit/api/test_identity_gate_single_source.py`。

    Raises:
        HTTPException: 认证失败
    """
    return _identityFromCredentialsOr401(credentials)


_SERVICE_TOKEN_HEADER = "X-Service-Token"
_API_KEY_HEADER = "X-API-Key"


def service_token_matches(provided: str) -> bool:
    """X-Service-Token 与 NEUROVA_SERVICE_TOKEN 常量时间比较。

    单一事实源：get_current_user_or_service 与 global_auth.GlobalAuthMiddleware
    共用本判定（未配置 env = 功能关闭，恒 False，无后门）。
    """
    import hmac as _hmac
    import os as _os

    expected = (_os.environ.get("NEUROVA_SERVICE_TOKEN") or "").strip()
    provided = str(provided or "").strip()
    return bool(expected and provided and _hmac.compare_digest(provided, expected))


async def get_current_user_or_service(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """FastAPI 依赖：JWT 优先，无 JWT 时接受服务令牌（遗留修复 ④）。

    面向无 JWT 的机器调用方（渠道后端、n8n、运维脚本等）访问知识条目 API：
    - 仅当环境变量 NEUROVA_SERVICE_TOKEN 已配置时启用（未配置=功能关闭，无后门）
    - 头 X-Service-Token 与配置值做常量时间比较（service_token_matches）
    - 匹配 → role="admin" 的受信机器身份（user_id="system"）
    - 服务令牌不匹配时回落 JWT 校验，两者都失败 → 401
    """
    if service_token_matches(request.headers.get(_SERVICE_TOKEN_HEADER, "")):
        return {
            "user_id": "system",
            "username": "service",
            "role": "admin",
            "neuser_id": "system",
            "tenant_id": "default",
            "auth_source": "service_token",
        }
    return await get_current_user(credentials)


async def get_current_user_or_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """FastAPI 依赖：JWT 优先，无 JWT 时接受外部 Agent API 密钥（凭证合一）。

    与 `get_current_user_or_service` 同族同规则：两类凭证**都不成立**才 401，
    绝不回落到 default 身份——外部 Agent 通信域的所有隔离键（user_id / agent_id）
    都以这份返回为准；端点里再解一次 header 就会与之同求异解（那正是 `bearer` 与
    `Bearer` 把同一枚凭证分进两个租户的成因）。

    密钥真相源只有一个：`api_key_manager.APIKeyManager`（持久化 + DCL 单例）。
    端点不得自持第二份密钥表——本域原来那张进程内 `_api_keys` 就是这么退役的。
    """
    if credentials:
        # 有 Bearer 就按 Bearer 判：有效则用，无效/过期由 get_current_user 直接 401。
        # 不做"JWT 失败再试密钥"的静默降级——那等于把一条坏凭证换成另一份身份。
        return await get_current_user(credentials)

    rawKey = (request.headers.get(_API_KEY_HEADER) or "").strip()
    if rawKey:
        from neurova.api.api_key_manager import get_api_key_manager

        apiKey = get_api_key_manager().validate_key(rawKey)
        if apiKey is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked or expired API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "user_id": apiKey.user_id,
            "username": f"apikey:{apiKey.name}",
            "role": "user",
            # 密钥只绑定到 user 一层，第二层按 `_user_identity` 的既有口径回退同一身份
            "neuser_id": apiKey.user_id,
            "agent_id": apiKey.agent_id,
            "key_id": apiKey.key_id,
            "tenant_id": str(getattr(apiKey, "tenant_id", "") or "default"),
            "auth_source": "api_key",
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """FastAPI 依赖：获取可选的认证用户（只认头）；未认证或凭证无效返回 None。"""
    return _identityFromCredentialsOrNone(credentials)


async def get_optional_userWithQueryToken(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(securityWithQuery),
) -> Optional[Dict[str, Any]]:
    """同 `get_optional_user`，但无头时回退 `?access_token=`（资源标签场景）。"""
    return _identityFromCredentialsOrNone(credentials)


_DEFAULT_USER = {"user_id": "default", "username": "default", "role": "user",
                 "neuser_id": "default", "tenant_id": "default"}


def _user_identity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 JWT payload 提取用户身份字典 (含 neuser_id)。

    审计修复 (P0-2): get_current_user 系列必须暴露 neuser_id,
    否则三层隔离第 2 层永远回退 "default"。存量 Token 无声明时
    回退 sub (即账号 id), 与新签发的 Token 语义一致。
    """
    sub = payload.get("sub", "unknown")
    tenant = payload.get("tenant_id") or payload.get("tenant") or "default"
    return {
        "user_id": sub,
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
        "neuser_id": payload.get("neuser_id") or sub,
        # 租户是数据分区键，不是另一条身份通道：随同一份身份字典下发，
        # 缺省落 default（匿名读与存量令牌语义不变）。
        "tenant_id": str(tenant or "default"),
    }


_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def requireIdentityForWrites(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """写类请求必须**带凭证**；读类请求原样放行（匿名读仍只见 default 桶）。

    为什么挂在这一处而不是逐个 handler 上：政策 2026-10-06 定的是"匿名共享 default 桶
    可以，但租户键必须是 user_id"——那是**读**侧语义。写侧沿用同一条回落等于把
    "共享桶"当成"无人看守的桶"：任何访客都能往同一个 `default` 租户里增删改，
    事后既无从对账也无从撤销（§6-1 身份批修的是"跨租户越权"，这一格是同一条链上
    "匿名可写"的另一半）。

    形态上刻意不做"依赖严格门本体"：路由级依赖对 GET 也会解析，那样会把政策要留的
    匿名读一起打死；凭证→身份这一步也不自解，直接调 `get_current_user` 用的同一份
    `_identityFromCredentialsOr401`，只是**只对写类方法**调用它。
    """
    if request.method in _READ_ONLY_METHODS:
        return _DEFAULT_USER.copy()
    return _identityFromCredentialsOr401(credentials)


#: **记忆面**允许出现的身份门名字（唯一清单，且刻意是闭集）。
#: 判据 `tests/unit/api/test_memoryWriteIdentityGate.py` 双向钉：清单里的名字必须
#: 真实存在，memory 包实际 import 的门必须都在清单内——第五道门自己长出来时会红。
#:
#: 为什么只有两道：政策 2026-10-06 记的是"读侧匿名可落 default 桶"（→
#: `get_current_user_or_default`）与"租户键必须是 user_id"（→ 严格门
#: `get_current_user`，写侧由 `requireIdentityForWrites` 复用它那份解析）。
#: 其余门（`WithQueryToken` / `or_api_key` / `or_service`）在全仓各有其用，
#: 但**记忆面一条都不该用**：查询串凭证会把 token 落进 URL 与访问日志，而
#: `X-Service-Token` 那条经 `semantic_search_api.py:114` 读记忆语料是**另一个面**
#: 的口径（登记在台账，不在本清单内）。
MEMORY_IDENTITY_GATES = (
    "get_current_user",
    "get_current_user_or_default",
)


async def get_current_user_or_default(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI 依赖：获取认证用户，无凭证时返回默认用户

    用于不需要严格认证但仍然想识别已登录用户的端点。

    BUG AUDIT S-10: 原实现对"凭证无效"也静默回落 default 身份——token
    过期/伪造/黑名单者变成共享 default 用户串改数据。现区分两种情况:
    - 完全无凭证 → 保留 _DEFAULT_USER 回落（桌面首启/登录前流程依赖）;
    - 有凭证但无效 → 401（与 get_current_user 同契约）。

    2026-10-08 记一格边界（P3-12 拍板"跨租户不可读"）：上面那条"无凭证回落 default"
    只对**读**成立。写类请求走 `requireIdentityForWrites`（同一条凭证链、同一份
    `_identityFromCredentialsOr401`），因为"共享 default 桶"不等于"无人看守的桶"——
    匿名写等于任何人都能改同一份数据，只是没人能对账。
    """
    if not credentials:
        return _DEFAULT_USER.copy()

    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _user_identity(payload)
