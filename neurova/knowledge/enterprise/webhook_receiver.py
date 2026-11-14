# -*- coding: utf-8 -*-
"""入站 webhook 接收器（specs/2026-11-12 §11 W10，D10 已裁）。

签名校验（HMAC-SHA256，密钥在源配置面 env 指针）＋时间戳窗口拒重放＋幂等键
去重（enterprise_webhook_dedup v49，unique(source_id, idempotency_key)）→
事件→descriptor→AdmissionRequest→admit（身份显式带 tenant/agent，不从
ContextVar 猜——AGENTS.md §3）；admit 拒记审计不重试风暴（fail-closed）；
缺省 off（`NEUROVA_KB_WEBHOOK_ENABLED`）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger
from neurova.core.time_utils import nowIso as _now

logger = get_logger(__name__)

#: webhook 总开关（缺省 off——新能力默认态＝旧行为）
WEBHOOK_ENV = "NEUROVA_KB_WEBHOOK_ENABLED"
#: 签名密钥 env 指针（U5 单源——rotate 写这里，接收面/模拟推送读这里；零明文落库）
WEBHOOK_SECRET_ENV = "NEUROVA_KB_WEBHOOK_SECRET"
#: 时间戳窗口（秒）——窗口外重放拒
TIMESTAMP_WINDOW_SECONDS = 300

_ON_VALUES = ("1", "true", "on", "yes")

_SCHEMA_V49_WEBHOOK_DEDUP = """
CREATE TABLE IF NOT EXISTS enterprise_webhook_dedup (
    source_id TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    received_at TEXT NOT NULL,
    fact_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_id, idempotency_key)
);
"""


def webhookEnabled() -> bool:
    return str(os.environ.get(WEBHOOK_ENV) or "").strip().lower() in _ON_VALUES


def computeSignature(body: bytes, timestamp: int, secret: str) -> str:
    """HMAC-SHA256(body + timestamp, secret)——签名体带时间戳（重放面收窄）。"""
    return hmac.new(secret.encode("utf-8"),
                    body + str(timestamp).encode("utf-8"),
                    hashlib.sha256).hexdigest()


class WebhookReceiver:
    """webhook 入站处理：签名→窗口→幂等→admit。"""

    def __init__(self, store: Any, secret: str = "", sourceId: str = "webhook",
                 agentId: str = "default", tenantId: str = "default") -> None:
        self._store = store
        self._secret = secret
        self._sourceId = sourceId
        self._agentId = agentId
        self._tenantId = tenantId
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def handle(self, body: bytes, timestamp: int, signature: str) -> Dict[str, Any]:
        """处理一次 webhook 调用：返回 admit 回执或诚实拒绝。"""
        if not webhookEnabled():
            return {"rejected": True,
                    "detail": "webhook 接收面缺省 off（%s 未开启）" % WEBHOOK_ENV}
        if not self._secret:
            return {"rejected": True, "detail": "webhook 密钥未配置（源配置面）"}
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return {"rejected": True, "detail": "timestamp 不可解析"}
        if abs(time.time() - ts) > TIMESTAMP_WINDOW_SECONDS:
            return {"rejected": True,
                    "detail": "时间戳超出 %d 秒窗口（重放拒）"
                              % TIMESTAMP_WINDOW_SECONDS}
        expected = computeSignature(body, ts, self._secret)
        if not hmac.compare_digest(expected, str(signature or "")):
            return {"rejected": True, "detail": "签名校验失败（HMAC-SHA256）"}
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload 非 JSON 对象")
        except (ValueError, UnicodeDecodeError) as exc:
            return {"rejected": True, "detail": "payload 不可解析：%s" % exc}
        idempotencyKey = str(payload.get("idempotency_key") or "").strip()
        if idempotencyKey:
            existing = self._lookupDedup(idempotencyKey)
            if existing is not None:
                return {"deduplicated": True, "fact_id": existing,
                        "detail": "幂等键已消费（零二次写）"}
        subject = str(payload.get("subject") or "").strip()
        predicate = str(payload.get("predicate") or "").strip()
        obj = str(payload.get("object") or "").strip()
        if not subject or not predicate or not obj:
            return {"rejected": True,
                    "detail": "payload 缺 subject/predicate/object"}
        from ..foundation.admission import AdmissionRequest, productionAdmissionGate

        content = "%s %s %s" % (subject, predicate, obj)
        try:
            gate = productionAdmissionGate(self._store, toolVersion="webhook_receiver")
            receipt = gate.admit(AdmissionRequest(
                agentId=self._agentId, tenantId=self._tenantId,
                subjectLabel=subject, predicateTermId=predicate,
                objectTerm=obj, content=content,
                assertions=[{"actorType": "pipeline",
                             "actorId": "webhook:%s" % self._sourceId,
                             "mediumRef": "webhook:%s" % self._sourceId,
                             "statementText": content}],
                activityKind="admit",
                activityBasis="webhook_receiver（源 %s）" % self._sourceId))
        except ValueError as exc:
            # fail-closed：拒即记审计（日志留名），不重试风暴
            logger.warning("webhook_receiver: admit 被拒（%s）——不重试", exc)
            return {"rejected": True, "detail": str(exc)}
        factId = receipt.factId
        if idempotencyKey:
            self._recordDedup(idempotencyKey, factId)
        return {"fact_id": factId, "subject_key": receipt.subjectKey,
                "activity_id": receipt.activityId}

    def _lookupDedup(self, key: str) -> Optional[str]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT fact_id FROM enterprise_webhook_dedup"
                " WHERE source_id = ? AND idempotency_key = ?",
                (self._sourceId, key)).fetchone()
        return str(row["fact_id"]) if row is not None else None

    def _recordDedup(self, key: str, factId: str) -> None:
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR IGNORE INTO enterprise_webhook_dedup"
                " (source_id, idempotency_key, received_at, fact_id)"
                " VALUES (?,?,?,?)",
                (self._sourceId, key, _now(), factId))
