"""
Webhook 入站触发业务逻辑（P1 Step 4b）

纯注入式设计：本模块不含任何存储层 import——trigger 加载、secret 解密、
workflow 加载、执行全部经 deps 注入（由装配方在启动时 set_deps_provider）。
安全链：查 trigger → enabled/type 校验 → HMAC 验签 → 限流 → 派发。
"""

import json
import logging
from typing import Any, Callable, Dict, Optional

from neurova.core.trigger_rate_limiter import TriggerRateLimiter
from neurova.core.webhook_security import verify_request, verify_signature

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Hub-Signature-256"

# 装配方注册的 deps 工厂（返回 load_trigger/load_published_workflow/
# decrypt_secret/run_workflow/rate_limiter_factory 五个可调用）
_DEPS_PROVIDER: Optional[Callable[[], Dict[str, Callable]]] = None


def set_deps_provider(provider: Callable[[], Dict[str, Callable]]) -> None:
    """注册默认 deps 工厂（应用启动装配时调用一次）。"""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


class IngressRejected(Exception):
    """入站被拒（携带 HTTP 状态码与原因码）。"""

    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


async def handle_webhook_ingress(
    trigger_id: str,
    payload: bytes,
    signature_header: Optional[str],
    deps: Optional[Dict[str, Callable]] = None,
    timestamp_header: Optional[str] = None,
) -> Dict[str, Any]:
    """处理一次 webhook 入站触发；被拒抛 IngressRejected，成功返回派发信封。

    deps 键：load_trigger / load_published_workflow / decrypt_secret /
             run_workflow / rate_limiter_for
    （rate_limiter_for(trigger) 须返回按 trigger 缓存的 limiter 实例，
      否则限流形同虚设——每请求新建桶永远全满。）

    P0-7/N3 重放防护：配置了 secret 的 trigger 走 verify_request——签名覆盖
    "<timestamp>." 前缀 + payload，且时间戳时效 300s；携带 X-Neurova-Timestamp
    的请求一律按新约定验签。未配置 secret（宽松模式）仍只拒伪造签名头。
    """
    d = deps or (_DEPS_PROVIDER() if _DEPS_PROVIDER else None)
    if d is None:
        raise IngressRejected(500, "INGRESS_NOT_CONFIGURED")

    trigger = d["load_trigger"](trigger_id)
    if trigger is None or not getattr(trigger, "enabled", False):
        raise IngressRejected(404, "TRIGGER_NOT_FOUND")
    if getattr(getattr(trigger, "type", None), "value", "") != "webhook":
        raise IngressRejected(404, "TRIGGER_NOT_FOUND")

    secret = ""
    encrypted = getattr(trigger, "secret_encrypted", None)
    if encrypted:
        try:
            secret = d["decrypt_secret"](encrypted)
        except Exception:
            logger.warning("trigger secret decrypt failed: %s", trigger_id)
        # 配置了 secret 的 trigger：必须验签（严格模式 + 重放防护）
        if timestamp_header:
            ok, reason = verify_request(payload, secret, signature_header, timestamp_header)
        else:
            ok = verify_signature(payload, secret, signature_header)
            reason = "OK" if ok else "INVALID_SIGNATURE"
        if not ok:
            # 统一 401/INVALID_SIGNATURE（细节进日志），交付审计侧视同签名无效
            logger.info("webhook signature rejected: %s %s", trigger_id, reason)
            raise IngressRejected(401, "INVALID_SIGNATURE")
    else:
        # 未配置 secret：开放 webhook（宽松模式），仅要求不携带伪造签名头
        if signature_header or timestamp_header:
            raise IngressRejected(401, "INVALID_SIGNATURE")

    limiter = d["rate_limiter_for"](trigger)
    if not limiter.acquire(trigger_id):
        raise IngressRejected(429, "RATE_LIMIT_EXCEEDED")

    try:
        body = json.loads(payload.decode("utf-8")) if payload else {}
    except Exception:
        raise IngressRejected(400, "INVALID_JSON")

    inputs = body.get("payload", body) if isinstance(body, dict) else {"payload": body}

    workflow = d["load_published_workflow"](trigger.workflow_id)
    if workflow is None:
        raise IngressRejected(404, "WORKFLOW_NOT_PUBLISHED")

    instance = await d["run_workflow"](workflow, inputs)
    status_value = getattr(instance, "status", None)
    return {
        "code": 0,
        "message": "Triggered",
        "data": {
            "trigger_id": trigger_id,
            "execution_id": getattr(instance, "id", None),
            "status": getattr(status_value, "value", None),
        },
    }
