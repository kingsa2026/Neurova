# -*- coding: utf-8 -*-
"""EKB 陈旧复验通道（H4，survey §10.2）——低置信/超期条目的再验证队列。

持久化会保存漏洞（survey §8.7）：陈旧经验若继续享受"照经验做"的默认信任，
就是漏洞的保鲜。本模块把**低置信/超期**条目收进再验证队列（纯读数＋队列
登记；复验动作由外部参考执行——F1/B2 通道取数），复验结果回写
evidence_state 由调用方执行（本模块不代写库，单一写口在 EKB 本体）。

判据（红灯判据的两半）：
- 陈旧条目在队列里被点名后，读者端不得把它们当"照经验做"的默认信任源
  （quality_snapshot 的 unevidenced_ratio 是既有的诚实面，队列另立名册）；
- 复验缺席保持现值不冒充：未复验的条目 evidence_state 不变，队列读数
  如实报 pending。
"""

import datetime
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 超期阈值（天）：入库时间早于此的条目进复验队列。
STALE_AFTER_DAYS = 30
#: 低置信阈值：confidence_score 低于此的条目进复验队列。
LOW_CONFIDENCE = 0.5


def revalidationQueue(ekb: Any, *, stale_after_days: int = STALE_AFTER_DAYS,
                      low_confidence: float = LOW_CONFIDENCE) -> Dict[str, Any]:
    """再验证队列读数（纯读数；零条目＝队列空，不是"都健康"）。

    ekb = ExperienceKnowledgeBase 实例（读面走其 _conn 既有单源；队列
    不另建第二份存储——名册即本读数的现算结果）。
    """
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=stale_after_days)).isoformat()
    with ekb._lock:
        rows = ekb._conn.execute(
            """
            SELECT id, skill_name, confidence_score, evidence_state, created_at
            FROM experience_records
            WHERE (confidence_score IS NULL OR confidence_score < ?)
               OR (created_at IS NOT NULL AND created_at < ?)
            ORDER BY created_at ASC
            """,
            (float(low_confidence), cutoff),
        ).fetchall()
    queue: List[Dict[str, Any]] = []
    for row in rows:
        queue.append({
            "id": row["id"],
            "skill_name": row["skill_name"],
            "confidence_score": row["confidence_score"],
            "evidence_state": row["evidence_state"],
            "created_at": row["created_at"],
        })
    return {
        "state": "measured" if queue else "empty",
        "queue_size": len(queue),
        "queue": queue[:50],
        "thresholds": {"stale_after_days": stale_after_days,
                       "low_confidence": low_confidence},
        "detail": (f"{len(queue)} 条低置信/超期条目待外部参考复验"
                   if queue else "无低置信/超期条目（复验队列为空，不读成全健康）"),
    }


def applyRevalidation(ekb: Any, record_id: int, *, verdict: str) -> bool:
    """复验结果回写 evidence_state（调用方在复验后执行；唯一写口走 EKB 本体）。

    verdict ∈ {evidenced, unevidenced}——复验确认的回 evidenced、复验不过的
    降 unevidenced；不改动其余字段（陈旧条目保持现值直至复验发生）。
    """
    if verdict not in ("evidenced", "unevidenced"):
        raise ValueError(f"复验结论非法：{verdict!r}（允许 evidenced/unevidenced）")
    with ekb._lock:
        cursor = ekb._conn.execute(
            "UPDATE experience_records SET evidence_state = ? WHERE id = ?",
            (verdict, int(record_id)),
        )
        ekb._conn.commit()
        updated = cursor.rowcount > 0
    if updated:
        logger.info("EKB 复验回写：record %s → %s", record_id, verdict)
    return updated
