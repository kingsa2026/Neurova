# -*- coding: utf-8 -*-
"""run 级范围凭据（C4：外部成员子进程身份绑定的纯逻辑层）。

背景：外部 agent 子进程此前以服务器身份运行，无 run 级身份绑定。本模块
签发/验证一种**范围凭据**：payload 绑定 ``run_id + tenant_id + exp``，
使子进程侧可证明「我属于哪个 run/租户」。

- 密钥**单源**：惰性取 ``neurova.api.auth.currentJwtSecretKey()``——全仓
  签名/验签密钥的唯一取值口（HTTP JWT 与本凭据同钥不同域，见下）。
- 令牌形状：``payload_b64url.sig_hex``；
  ``payload = base64url(json{"run_id","tenant_id","exp"})``，
  ``sig = HMAC-SHA256(密钥, 域前缀 + payload_b64url)``。
  域前缀隔离：同一密钥下的 HTTP JWT（HS256）与本凭据互不可冒充。
- fail-closed：``verifyRunCredential`` 对格式/签名/过期任一不符一律返回
  ``None``（不抛）；``issueRunCredential`` 对缺参诚实抛 ``ValueError``，
  绝不签发无绑定的凭据。
- HTTP 消费面（哪个端点接受该凭据）留待有真实环境时另卡。
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

#: 缺省有效期：24 小时（外部成员单轮任务量级；到期由 verify 拒绝）。
DEFAULT_RUN_CREDENTIAL_TTL_S = 86400

#: 签名域前缀：把「run 凭据」与同钥的 HTTP JWT 在签名输入上隔离开。
_SIGN_DOMAIN = b"neurova-run-credential-v1:"


def _signingKey() -> bytes:
    """取签名密钥（惰性单源）：经 ``currentJwtSecretKey``，不本地复制密钥。"""
    from neurova.api.auth import currentJwtSecretKey

    return str(currentJwtSecretKey()).encode("utf-8")


def _encodePayload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _signPayload(key: bytes, payloadB64: str) -> str:
    message = _SIGN_DOMAIN + payloadB64.encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def issueRunCredential(
    run_id: str,
    tenant_id: str,
    *,
    ttl_s: float = DEFAULT_RUN_CREDENTIAL_TTL_S,
) -> str:
    """签发绑定 ``run_id + tenant_id`` 的 run 级凭据。

    Args:
        run_id: run 标识（外部成员场景即 ``subagent_id``）。
        tenant_id: 租户标识（外部成员场景即 ``run.tenant_id``）。
        ttl_s: 有效期秒数，缺省 24h；<=0 产生即期作废的凭据（验证侧必拒）。

    Returns:
        ``payload_b64url.sig_hex`` 形式的令牌字符串。

    Raises:
        ValueError: ``run_id``/``tenant_id`` 缺失或空白——fail-closed，
            不签发无绑定凭据。
    """
    rid = str(run_id or "").strip()
    tid = str(tenant_id or "").strip()
    if not rid or not tid:
        raise ValueError(
            "拒绝签发 run 凭据：run_id 与 tenant_id 均为必填"
            f"（run_id={run_id!r}, tenant_id={tenant_id!r}）"
        )
    payload = {"run_id": rid, "tenant_id": tid, "exp": time.time() + float(ttl_s)}
    payloadB64 = _encodePayload(payload)
    return f"{payloadB64}.{_signPayload(_signingKey(), payloadB64)}"


def verifyRunCredential(token: Optional[str]) -> Optional[dict]:
    """验证 run 级凭据，通过则返回 ``{"run_id","tenant_id"}``。

    fail-closed：token 形状/签名/有效期任一不符（含 None、非串、坏
    base64、坏 JSON、字段缺失）一律返回 ``None``，不抛异常——消费方
    拿到 ``None`` 即应拒绝该子进程的 run 级主张。
    """
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    payloadB64, sig = parts
    # 常量时间比较：签名逐字节核对，不因首字节失配提前暴露时长侧信道。
    expected = _signPayload(_signingKey(), payloadB64)
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payloadB64.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return None  # 坏 base64 / 坏 JSON：格式不符，fail-closed
    if not isinstance(payload, dict):
        return None
    rid = payload.get("run_id")
    tid = payload.get("tenant_id")
    exp = payload.get("exp")
    if not isinstance(rid, str) or not rid:
        return None
    if not isinstance(tid, str) or not tid:
        return None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    if time.time() >= exp:
        return None  # 过期
    return {"run_id": rid, "tenant_id": tid}
