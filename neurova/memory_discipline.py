"""记忆重纪律（S16 D2）——3-Task 候选转正 / 世代失效 / 人工审阅接通。

增量层设计（主干敬畏 A14：零 MemoryManager 内部结构改动、零 schema 变更、
零生命周期枚举扩容）：

存储落点 = 主记忆行 ``metadata["memoryDiscipline"]``（JSON 列内自由结构）：
- 新行（带来源任务/会话）→ ``{"status": "candidate", "taskKeys": [...],
  "firstObservedAt": iso}``；lifecycle 保持 ACTIVE——候选语义可见（经
  to_dict 的 metadata 自然流出），既有读路径（recall/get_memories）不变。
- 再观测 = MemoryManager.remember 的内容门命中既有行（同作用域+归一化内容
  +分类维度），taskKeys 去重追加；跨 ≥ ``MEMORY_PROMOTION_MIN_TASKS`` 个
  独立任务 → ``status: "promoted"``（转正判定单点 = 本模块观察簿记）。
- 世代失效 = 新事实与旧记忆经 :func:`judgeClauseConflict`（全仓唯一确定性
  冲突判据，零模型调用）判出矛盾 → 旧行 ``{"status": "superseded",
  "supersededBy": <新行id>, "supersededAt", "supersededBasis"}`` 且
  lifecycle_stage=forgotten（退出召回、按 id 可追溯、不物理删）。
- 无任务/会话上下文的写入（API 人工直写、pending confirm）= 显式人工意图，
  不进候选（直接持久）；世代失效仍生效。

人工审阅接通（S7 移交项）：pending_memories 的 propose/confirm 两点接入
:func:`screenMemoryContent`——store 提议命中敏感模式族即落 ``sensitive_rule``
标记 + 审计；confirm 对敏感候选要求显式 ``allow_sensitive=True``（缺省诚实
报错，绝不静默放行），显式放行经 :func:`memoryAdmissionRelease` 作用域令牌
过 S7 准入闸，放行人/规则/依据审计留痕。

门控：``NEUROVA_MEMORY_DISCIPLINE``（默认 off）。关闭时包装器单布尔检查后
直通——行为与现状完全一致。
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────
# 常量（截断/阈值一律具名，不散落字面量）
# ──────────────────────────────────────────────────────────────

#: 门控环境变量（进程启动时读一次作初值；运行期用 setter 调整）
DISCIPLINE_ENV = "NEUROVA_MEMORY_DISCIPLINE"

#: 转正门槛：跨 ≥3 个独立任务再观测才转正为持久记忆
MEMORY_PROMOTION_MIN_TASKS = 3

#: 世代失效的矛盾扫描窗口（get_memories 按 created_at DESC 的有界上限）
SUPERSESSION_SCAN_LIMIT = 200

#: 候选/世代状态的 metadata 键（唯一落点）
DISCIPLINE_META_KEY = "memoryDiscipline"

STATUS_CANDIDATE = "candidate"
STATUS_PROMOTED = "promoted"
STATUS_SUPERSEDED = "superseded"

#: 任务键取值优先级（具名单一口径）：task_id > run_id > session_id
TASK_KEY_FIELDS = ("task_id", "run_id", "session_id")

#: installMemoryDiscipline 的幂等标记属性名
DISCIPLINE_MARKER_ATTR = "_memoryDisciplineGated"

#: 审计 action 标识（复用仓内审计单源 neurova.security.audit_logger）
AUDIT_PROPOSED_ACTION = "memory_pending.sensitive_proposed"
AUDIT_RELEASED_ACTION = "memory_pending.sensitive_released"
AUDIT_REJECTED_ACTION = "memory_pending.sensitive_rejected"

_TRUTHY = ("1", "true", "on", "yes")

# ──────────────────────────────────────────────────────────────
# 门控状态与计数
# ──────────────────────────────────────────────────────────────

_enabled = str(os.environ.get(DISCIPLINE_ENV, "")).strip().lower() in _TRUTHY
_enabledLock = threading.Lock()

_counters: Dict[str, int] = {
    "candidateMarked": 0,
    "observationRecorded": 0,
    "promoted": 0,
    "superseded": 0,
    "pendingSensitiveProposed": 0,
    "pendingSensitiveReleased": 0,
    "pendingSensitiveRejected": 0,
}
_countersLock = threading.Lock()


def memoryDisciplineEnabled() -> bool:
    with _enabledLock:
        return _enabled


def setMemoryDisciplineEnabled(enabled: bool) -> bool:
    """设置重纪律门控（运行期开关）。True=开启候选/世代/审阅纪律；False=现状行为。"""
    global _enabled
    with _enabledLock:
        _enabled = bool(enabled)
    logger.warning("记忆重纪律门控已切换为 %s", "on" if _enabled else "off")
    return _enabled


def disciplineCounters() -> dict:
    """进程内纪律计数快照（候选/观测/转正/失效/敏感审阅）。"""
    with _countersLock:
        return dict(_counters)


def _bumpCounter(name: str) -> None:
    with _countersLock:
        _counters[name] = _counters.get(name, 0) + 1


# ──────────────────────────────────────────────────────────────
# 审计（复用仓内审计单源；写失败降级为错误日志+计数，绝不阻断主流程）
# ──────────────────────────────────────────────────────────────


def _auditDisciplineEvent(action: str, details: dict) -> None:
    try:
        from neurova.core.identity_context import get_request_user_id
        from neurova.security.audit_logger import (
            AuditEventType,
            AuditSeverity,
            log_audit,
        )

        ok = log_audit(
            AuditEventType.SECURITY_EVENT,
            AuditSeverity.MEDIUM,
            user_id=str(get_request_user_id() or ""),
            action=action,
            details=details,
            resource_type="memory",
        )
        if not ok:
            logger.error("记忆重纪律审计未落库（action=%s）——须人工复核", action)
    except Exception as exc:  # noqa: BLE001 - 审计异常不得影响纪律判定
        logger.error("记忆重纪律审计异常（action=%s）：%s", action, exc)


# ──────────────────────────────────────────────────────────────
# 任务键解析与候选簿记
# ──────────────────────────────────────────────────────────────


def resolveTaskKey(metadata: Any) -> Optional[str]:
    """从写入 metadata 解析来源任务键：task_id > run_id > session_id，缺省 None。"""
    if not isinstance(metadata, dict):
        return None
    for field in TASK_KEY_FIELDS:
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _nowIso() -> str:
    return datetime.now(UTC).isoformat()


def _createdAfter(createdIso: Any, t0: datetime) -> bool:
    """行是否本次新建：created_at 晚于写前时刻（内容门命中行的 created_at 必旧于 t0）。"""
    if not isinstance(createdIso, str) or not createdIso:
        return False
    try:
        created = datetime.fromisoformat(createdIso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created >= t0


def _markCandidate(manager: Any, memId: str, taskKey: str) -> None:
    """新行标入候选（lifecycle 保持 ACTIVE——候选语义可见，读路径不变）。"""
    updated = manager.update_memory(
        memId,
        metadata={
            DISCIPLINE_META_KEY: {
                "status": STATUS_CANDIDATE,
                "taskKeys": [taskKey],
                "firstObservedAt": _nowIso(),
            }
        },
    )
    if updated:
        _bumpCounter("candidateMarked")
        logger.debug("记忆重纪律：新观测标入候选 mem=%s task=%s", memId, taskKey)


def _recordObservation(manager: Any, row: Dict[str, Any], taskKey: str) -> None:
    """再观测簿记：taskKeys 去重追加；跨任务数达门槛即转正（判定单点）。"""
    disc = (row.get("metadata") or {}).get(DISCIPLINE_META_KEY)
    if not isinstance(disc, dict) or disc.get("status") != STATUS_CANDIDATE:
        return
    taskKeys = [k for k in disc.get("taskKeys") or [] if isinstance(k, str)]
    if taskKey in taskKeys:
        return
    taskKeys.append(taskKey)
    updated_disc = dict(disc)
    updated_disc["taskKeys"] = taskKeys
    if len(taskKeys) >= MEMORY_PROMOTION_MIN_TASKS:
        updated_disc["status"] = STATUS_PROMOTED
        updated_disc["promotedAt"] = _nowIso()
        _bumpCounter("promoted")
        logger.info(
            "记忆重纪律：候选转正 mem=%s 跨任务数=%s", row.get("id"), len(taskKeys)
        )
    else:
        _bumpCounter("observationRecorded")
    manager.update_memory(str(row.get("id")), metadata={DISCIPLINE_META_KEY: updated_disc})


def _supersedeContradictions(manager: Any, newId: str, content: str) -> None:
    """世代失效：新事实与窗口内活跃记忆判出矛盾 → 旧代标记 superseded（可追溯，不物理删）。

    扫描窗口 = get_memories(created_at DESC, SUPERSESSION_SCAN_LIMIT)（排除已
    遗忘/已失效行）；判据复用 judgeClauseConflict 单源（教义第 6 条）。
    """
    try:
        from neurova.cognitive_layers.memory_layer.conflict import judgeClauseConflict
    except Exception as exc:  # noqa: BLE001 - 判据缺席不阻断写入
        logger.warning("记忆重纪律：冲突判据不可用，跳过世代失效检查: %s", exc)
        return
    try:
        window = manager.get_memories(limit=SUPERSESSION_SCAN_LIMIT) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆重纪律：矛盾扫描窗口读取失败: %s", exc)
        return
    for row in window:
        if not isinstance(row, dict):
            continue
        rowId = str(row.get("id") or "")
        if not rowId or rowId == newId:
            continue
        rowContent = str(row.get("content") or "")
        if not rowContent:
            continue
        try:
            hit = judgeClauseConflict(content, rowContent)
        except Exception as exc:  # noqa: BLE001 - 单对判定失败不阻断整窗
            logger.debug("记忆重纪律：单对矛盾判定失败 %s: %s", rowId, exc)
            continue
        if hit is None:
            continue
        _bumpCounter("superseded")
        oldDisc = (row.get("metadata") or {}).get(DISCIPLINE_META_KEY)
        merged = dict(oldDisc) if isinstance(oldDisc, dict) else {}
        merged.update(
            {
                "status": STATUS_SUPERSEDED,
                "supersededBy": newId,
                "supersededAt": _nowIso(),
                "supersededBasis": str(hit[3]),
            }
        )
        ok = manager.update_memory(
            rowId, lifecycle_stage="forgotten", metadata={DISCIPLINE_META_KEY: merged}
        )
        logger.info(
            "记忆重纪律：旧代已失效 mem=%s supersededBy=%s basis=%s ok=%s",
            rowId,
            newId,
            str(hit[3]),
            ok,
        )


def observeWrite(
    manager: Any, memId: str, content: str, metadata: Any, t0: datetime
) -> None:
    """一次 remember 写入后的纪律簿记（候选/观测/转正/世代失效）。

    fail-soft：任何簿记异常只留日志与计数，绝不阻断写入主链路。
    """
    if not manager or not memId:
        return
    try:
        # get_memory 的 touch 语义（温度强化）与"再观测"同向；created_at 不受影响
        row = manager.get_memory(str(memId))
        if not isinstance(row, dict):
            return
        fresh = _createdAfter(row.get("created_at"), t0)
        taskKey = resolveTaskKey(metadata)
        if fresh:
            if taskKey:
                _markCandidate(manager, str(memId), taskKey)
            _supersedeContradictions(manager, str(memId), str(content or ""))
        elif taskKey:
            _recordObservation(manager, row, taskKey)
    except Exception as exc:  # noqa: BLE001 - 纪律故障绝不阻断写入
        logger.warning("记忆重纪律簿记失败（写入不受影响）: %s", exc, exc_info=True)


# ──────────────────────────────────────────────────────────────
# 人工审阅接通（pending_memories propose/confirm 两点）
# ──────────────────────────────────────────────────────────────


def screenPendingProposal(content: str):
    """propose 点筛查：门控开启时过敏感模式族，命中返回 SensitiveHit，否则 None。

    关闭态恒 None（行为与现状完全一致）。
    """
    if not memoryDisciplineEnabled():
        return None
    from neurova.memory_admission import screenMemoryContent

    return screenMemoryContent(content)


def auditPendingSensitiveProposed(record: Dict[str, Any], hit) -> None:
    """敏感候选进入待审队列的拦截留痕。"""
    _bumpCounter("pendingSensitiveProposed")
    _auditDisciplineEvent(
        AUDIT_PROPOSED_ACTION,
        {
            "pendingId": str(record.get("id") or ""),
            "rule": getattr(hit, "ruleName", ""),
            "excerpt": getattr(hit, "redactedExcerpt", ""),
            "proposedBy": str(record.get("proposed_by") or ""),
        },
    )


def auditPendingSensitiveReleased(record: Dict[str, Any], hit, decidedBy: str) -> None:
    """人工显式放行敏感候选的留痕。"""
    _bumpCounter("pendingSensitiveReleased")
    _auditDisciplineEvent(
        AUDIT_RELEASED_ACTION,
        {
            "pendingId": str(record.get("id") or ""),
            "rule": getattr(hit, "ruleName", "") or str(record.get("sensitive_rule") or ""),
            "excerpt": getattr(hit, "redactedExcerpt", ""),
            "decidedBy": str(decidedBy or ""),
            "memoryId": str(record.get("memory_id") or ""),
        },
    )


def auditPendingSensitiveRejected(record: Dict[str, Any], decidedBy: str) -> None:
    """人工拒收敏感候选的留痕。"""
    _bumpCounter("pendingSensitiveRejected")
    _auditDisciplineEvent(
        AUDIT_REJECTED_ACTION,
        {
            "pendingId": str(record.get("id") or ""),
            "rule": str(record.get("sensitive_rule") or ""),
            "decidedBy": str(decidedBy or ""),
        },
    )


# ──────────────────────────────────────────────────────────────
# 单点包一层：把 memory_manager 的 remember 写入口装上纪律簿记
# ──────────────────────────────────────────────────────────────


def _extractRememberMetadata(args: tuple, kwargs: dict) -> Any:
    """从 remember 调用里取 metadata：显式 kwarg 优先，其次首个 dict 位置参。"""
    metadata = kwargs.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    for arg in args:
        if isinstance(arg, dict):
            return arg
    return None


def installMemoryDiscipline(memoryManager: Any) -> Any:
    """给 memory_manager 的 remember 写入口包一层纪律簿记（幂等，原地包装）。

    生产装配点：MemCore.memory_manager setter（与 S7 准入闸同一装配点，
    准入闸在内层、纪律簿记在外层）。返回原实例，不替换对象、不改内部结构；
    门控关闭时单布尔检查后直通——行为与现状完全一致。
    """
    if memoryManager is None:
        return None
    if getattr(memoryManager, DISCIPLINE_MARKER_ATTR, False):
        return memoryManager
    originalRemember = memoryManager.remember

    def disciplinedRemember(*args, **kwargs):
        t0 = datetime.now(UTC)
        memId = originalRemember(*args, **kwargs)
        if memoryDisciplineEnabled():
            content = kwargs.get("content")
            if content is None:
                from neurova.memory_admission import _extractRememberContent

                content = _extractRememberContent(args, kwargs)
            observeWrite(
                memoryManager,
                memId,
                content if isinstance(content, str) else str(content or ""),
                _extractRememberMetadata(args, kwargs),
                t0,
            )
        return memId

    try:
        memoryManager.remember = disciplinedRemember
        setattr(memoryManager, DISCIPLINE_MARKER_ATTR, True)
    except Exception as exc:  # noqa: BLE001 - 只读对象装不上层时保持原样并留痕
        logger.error("记忆重纪律装配失败（remember 未包层）：%s", exc)
        return memoryManager
    logger.debug("记忆重纪律已装配：remember 写入口已包层（门控 %s）", "on" if _enabled else "off")
    return memoryManager
