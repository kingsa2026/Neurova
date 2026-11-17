"""记忆准入（S7 轻量先行）——写入前拦截 + 准入清单提示词。

两道闸（写入前、单点）：
1. **敏感信息正则拦截**：api key / token / password / 私钥模式族命中即拒收。
   审计落 `neurova.security.audit_logger`（仓内审计单源），同时附结构化日志
   与进程内计数；审计写失败不阻断拒收判定（宁可拒收可查，不可静默放行）。
2. **准入清单提示词**：模型可见守则（该记：用户明确偏好/事实；不记：一次性
   感想/中间过程；绝不记：密钥凭据）。本模块是清单文本的唯一事实源；拒收
   反馈（异常消息 / memory 技能 store 的 error 回显）内嵌清单，使守则出现在
   写入链路的提示面上——模型在写入被拦时当场看到该记与绝不记的边界。

单点包一层：`MemCore.memory_manager` 装配点经 :func:`installMemoryAdmission`
把 `remember` 写入口统一过闸。chat 主路（post_chat_pipeline → remember）、
mem_core.save_conversation_memory、memory 技能 store、API 记忆写入、缓冲
队列落库全部汇到同一 memory_manager 实例的 remember，一处包层全链路生效。

放行通道：:func:`setMemoryAdmissionPolicy`（或环境变量
``NEUROVA_MEMORY_ADMISSION``）。``enforce``（默认）命中即拒收；``audit``
放行但逐条留痕计数；``off`` 运行期紧急开关（仍有 debug 日志，不静默）。
S16 人工审阅接通后另有作用域放行令牌 :func:`memoryAdmissionRelease`——仅供
pending confirm 的人工显式放行使用，放行逐次留痕，不改变全局策略。
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from typing import Any, NamedTuple, Optional, Tuple

from neurova.core.identity_context import get_request_user_id
from neurova.core.logger import get_logger
from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────
# 常量（截断/阈值一律具名，不散落字面量）
# ──────────────────────────────────────────────────────────────

#: 拒收审计在审计单源里的 action 标识
MEMORY_ADMISSION_REJECT_ACTION = "memory_admission.rejected"

#: 拒收摘要里密钥匹配段之外的上下文字符数（前后各留一点，便于人工定位误杀）
EXCERPT_CONTEXT_CHARS = 24

#: 脱敏时保留的密钥头部/尾部字符数（中间以 *** 遮蔽）
REDACT_KEEP_HEAD_CHARS = 4
REDACT_KEEP_TAIL_CHARS = 2
REDACT_MASK = "***"

#: 摘要首尾的省略标记
EXCERPT_ELLIPSIS = "…"

#: 准入策略环境变量（进程启动时读一次作初值；运行期用 setter 调整）
ADMISSION_POLICY_ENV = "NEUROVA_MEMORY_ADMISSION"

POLICY_ENFORCE = "enforce"
POLICY_AUDIT_ONLY = "audit"
POLICY_DISABLED = "off"
VALID_ADMISSION_POLICIES: Tuple[str, ...] = (
    POLICY_ENFORCE,
    POLICY_AUDIT_ONLY,
    POLICY_DISABLED,
)

#: installMemoryAdmission 的幂等标记属性名
ADMISSION_MARKER_ATTR = "_memoryAdmissionGated"

# ──────────────────────────────────────────────────────────────
# 敏感信息模式族（具名常量，命中规则名随审计/日志/异常一起给出，可解释）
# ──────────────────────────────────────────────────────────────


class SensitivePattern(NamedTuple):
    """一条敏感信息规则：ruleName 用于审计与误杀复核，regex 为匹配式。"""

    ruleName: str
    regex: "re.Pattern[str]"


_SENSITIVE_PATTERN_SPEC: Tuple[Tuple[str, str], ...] = (
    # PEM 私钥（RSA/EC/OPENSSH/PGP/DSA 等）
    ("privateKeyPem", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # Anthropic 样式 key（先于通用 sk- 命名，便于解释）
    ("anthropicKey", r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"),
    # OpenAI 样式 key（含 sk-proj-/sk-svcacct-/sk-admin- 前缀；假样式 sk-test-fake-123 亦命中）
    ("openaiStyleKey", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{8,}\b"),
    # GitHub token（ghp_/gho_/ghu_/ghs_/ghr_）
    ("githubToken", r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    # AWS Access Key ID
    ("awsAccessKeyId", r"\bAKIA[0-9A-Z]{16}\b"),
    # Slack token（xoxb-/xoxa-/xoxp-/xoxr-/xoxs-）
    ("slackToken", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    # JWT 三段式
    ("jwtCredential", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),
    # Bearer 凭据
    ("bearerToken", r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
    # 键值式凭据赋值（password=xxx / api-key: xxx / client_secret=xxx 等）
    (
        "credentialAssignment",
        r"\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|secret[_-]?key"
        r"|client[_-]?secret|private[_-]?key|password|passwd|pwd)\b\s*[:=]\s*[^\s]{3,}",
    ),
    # 中文凭据标签（密码：xxx / 密钥是 xxx / 访问令牌：xxx 等）
    ("credentialAssignmentCn", r"(?:密码|口令|密钥|秘钥|访问令牌)\s*[:：是]\s*[^\s]{3,}"),
)

#: 敏感信息模式族（本模块唯一正则集中地；写入前拦截逐条匹配，首条命中即报）
SENSITIVE_KEY_PATTERNS: Tuple[SensitivePattern, ...] = tuple(
    SensitivePattern(ruleName=name, regex=re.compile(pattern))
    for name, pattern in _SENSITIVE_PATTERN_SPEC
)

# ──────────────────────────────────────────────────────────────
# 准入清单提示词（唯一事实源）
# ──────────────────────────────────────────────────────────────

ADMISSION_CHECKLIST_PROMPT = (
    "## 记忆准入清单\n"
    "写入长期记忆前逐条核对：\n"
    "- 该记：用户明确表达的偏好、稳定事实、重要约定与决策结论\n"
    "- 不记：一次性感想、客套话、中间推理过程、临时任务状态\n"
    "- 绝不记：密钥、token、密码、私钥等敏感凭据，这类内容一律不得进入记忆\n"
    "- 拿不准时先向用户确认，不要默认写入"
)


def admissionChecklistPrompt() -> str:
    """准入清单提示词（模型可见守则）。

    清单文本的唯一事实源：拒收反馈内嵌本清单；提示词装配面（规则段/
    工具描述）如需展示守则，一律从本函数取，不得另写一份。
    """
    return ADMISSION_CHECKLIST_PROMPT


# ──────────────────────────────────────────────────────────────
# 命中结果与脱敏摘要
# ──────────────────────────────────────────────────────────────


class SensitiveHit(NamedTuple):
    """一次敏感命中：规则名 + 脱敏后的原文摘要（供人工复核误杀）。"""

    ruleName: str
    redactedExcerpt: str


def redactSecret(secretText: str) -> str:
    """遮蔽密钥本体：保留首尾少量字符，中间以 *** 代替。"""
    keepHead = REDACT_KEEP_HEAD_CHARS
    keepTail = REDACT_KEEP_TAIL_CHARS
    if len(secretText) <= keepHead + keepTail:
        return REDACT_MASK
    return secretText[:keepHead] + REDACT_MASK + secretText[-keepTail:]


def buildRedactedExcerpt(content: str, match: "re.Match[str]") -> str:
    """以命中点为中心取一小段原文，密钥本体脱敏后返回。"""
    start = max(0, match.start() - EXCERPT_CONTEXT_CHARS)
    end = min(len(content), match.end() + EXCERPT_CONTEXT_CHARS)
    head = EXCERPT_ELLIPSIS if start > 0 else ""
    tail = EXCERPT_ELLIPSIS if end < len(content) else ""
    body = (
        content[start : match.start()]
        + redactSecret(match.group(0))
        + content[match.end() : end]
    )
    return head + body + tail


def screenMemoryContent(content: str) -> Optional[SensitiveHit]:
    """写入前筛查：命中敏感模式族返回 SensitiveHit，否则 None。"""
    if not content or not isinstance(content, str):
        return None
    for pattern in SENSITIVE_KEY_PATTERNS:
        matched = pattern.regex.search(content)
        if matched:
            return SensitiveHit(
                ruleName=pattern.ruleName,
                redactedExcerpt=buildRedactedExcerpt(content, matched),
            )
    return None


# ──────────────────────────────────────────────────────────────
# 策略（放行通道）与计数
# ──────────────────────────────────────────────────────────────

_admissionPolicy = os.environ.get(ADMISSION_POLICY_ENV, POLICY_ENFORCE).strip().lower()
if _admissionPolicy not in VALID_ADMISSION_POLICIES:
    logger.warning(
        "环境变量 %s 取值非法（%s），回落默认策略 %s",
        ADMISSION_POLICY_ENV,
        _admissionPolicy,
        POLICY_ENFORCE,
    )
    _admissionPolicy = POLICY_ENFORCE

_policyLock = threading.Lock()

_counters = {
    "sensitiveHits": 0,
    "rejected": 0,
    "auditOnlyPassed": 0,
    "auditWriteFailures": 0,
    "releasedSensitiveWrites": 0,
}
_countersLock = threading.Lock()


def currentAdmissionPolicy() -> str:
    with _policyLock:
        return _admissionPolicy


def setMemoryAdmissionPolicy(policy: str) -> str:
    """设置准入策略（放行通道）。enforce=拒收；audit=放行但留痕；off=紧急开关。"""
    global _admissionPolicy
    normalized = str(policy or "").strip().lower()
    if normalized not in VALID_ADMISSION_POLICIES:
        raise ValueError(
            f"非法准入策略：{policy!r}，可选值 {VALID_ADMISSION_POLICIES}"
        )
    with _policyLock:
        _admissionPolicy = normalized
    logger.warning("记忆准入策略已切换为 %s", normalized)
    return normalized


def admissionCounters() -> dict:
    """进程内准入计数快照（命中/拒收/放行留痕/审计落库失败）。"""
    with _countersLock:
        return dict(_counters)


def _bumpCounter(name: str) -> None:
    with _countersLock:
        _counters[name] = _counters.get(name, 0) + 1


# ──────────────────────────────────────────────────────────────
# 审计（复用仓内审计单源 neurova.security.audit_logger）
# ──────────────────────────────────────────────────────────────


def _recordRejectionAudit(hit: SensitiveHit, contentLength: int, origin: str, policy: str) -> None:
    """拒收/放行留痕写入审计单源；写失败降级为错误日志+计数，绝不阻断主流程。"""
    details = {
        "rule": hit.ruleName,
        "excerpt": hit.redactedExcerpt,
        "contentLength": contentLength,
        "origin": origin,
        "policy": policy,
    }
    try:
        ok = log_audit(
            AuditEventType.SECURITY_EVENT,
            AuditSeverity.MEDIUM,
            user_id=str(get_request_user_id() or ""),
            action=MEMORY_ADMISSION_REJECT_ACTION,
            details=details,
            resource_type="memory",
        )
    except Exception as exc:  # noqa: BLE001 - 审计异常不得影响准入判定
        logger.error("记忆准入审计异常（%s）：%s", hit.ruleName, exc)
        ok = False
    if not ok:
        _bumpCounter("auditWriteFailures")
        logger.error(
            "记忆准入审计未落库（rule=%s excerpt=%s）——判定已生效，这条须人工复核",
            hit.ruleName,
            hit.redactedExcerpt,
        )


# ──────────────────────────────────────────────────────────────
# 人工放行令牌（S16 人工审阅接通：pending confirm 显式放行敏感候选的唯一通道）
# ──────────────────────────────────────────────────────────────

_releaseState = threading.local()


@contextmanager
def memoryAdmissionRelease():
    """作用域内放行一次敏感写入（S16 人工审阅：pending confirm 显式放行用）。

    仅显式人工决定（allow_sensitive=True 的 confirm）允许进入本作用域，
    且放行本身逐次审计留痕（releasedSensitiveWrites 计数 + 审计单源），
    绝不静默放行。作用域退出即恢复原策略（不黏连、不全局改策）。
    """
    _releaseState.active = True
    try:
        yield
    finally:
        _releaseState.active = False


def _releaseTokenActive() -> bool:
    return bool(getattr(_releaseState, "active", False))


# ──────────────────────────────────────────────────────────────
# 准入异常与强制闸
# ──────────────────────────────────────────────────────────────


class MemoryAdmissionRejected(RuntimeError):
    """敏感信息写入被拒。消息内嵌命中规则、脱敏摘要与准入清单（可解释）。"""

    def __init__(self, violation: SensitiveHit):
        self.violation = violation
        super().__init__(
            f"记忆准入拒收（规则 {violation.ruleName}）：命中内容摘要"
            f"「{violation.redactedExcerpt}」。{admissionChecklistPrompt()}"
        )


def enforceMemoryAdmission(content: Any, *, origin: str = "") -> Any:
    """写入前强制闸：敏感命中按策略处置，通过则原样返回 content。

    - enforce（默认）：审计留痕 + 拒收（抛 MemoryAdmissionRejected）；
    - audit：审计留痕 + 放行（计数 auditOnlyPassed，不静默）；
    - off：紧急开关，debug 日志后放行（不留审计）。
    """
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    policy = currentAdmissionPolicy()
    if policy == POLICY_DISABLED:
        logger.debug("记忆准入已关闭（off），放行本次写入：origin=%s", origin)
        return content
    hit = screenMemoryContent(text)
    if hit is None:
        return content
    _bumpCounter("sensitiveHits")
    _recordRejectionAudit(hit, len(text), origin, policy)
    if _releaseTokenActive():
        # S16 人工审阅接通：显式放行作用域内的敏感写入（留痕后放行，不静默）
        _bumpCounter("releasedSensitiveWrites")
        logger.warning(
            "记忆准入人工放行：rule=%s origin=%s excerpt=%s（人工显式决定，留痕）",
            hit.ruleName,
            origin,
            hit.redactedExcerpt,
        )
        return content
    logger.warning(
        "记忆准入拒收：rule=%s origin=%s policy=%s excerpt=%s",
        hit.ruleName,
        origin,
        policy,
        hit.redactedExcerpt,
    )
    if policy == POLICY_AUDIT_ONLY:
        _bumpCounter("auditOnlyPassed")
        return content
    _bumpCounter("rejected")
    raise MemoryAdmissionRejected(hit)


# ──────────────────────────────────────────────────────────────
# 单点包一层：把 memory_manager 的 remember 写入口装上闸
# ──────────────────────────────────────────────────────────────


def _extractRememberContent(args: tuple, kwargs: dict) -> Any:
    """从 remember 调用里取 content：显式 kwarg 优先，其次首个字符串位置参。"""
    if "content" in kwargs:
        return kwargs["content"]
    for arg in args:
        if isinstance(arg, str):
            return arg
    return ""


def installMemoryAdmission(memoryManager: Any) -> Any:
    """给 memory_manager 的 remember 写入口包一层准入闸（幂等，原地包装）。

    生产装配点：MemCore.memory_manager setter。凡经 MemCore 装配的
    memory_manager，其 remember（chat 主路、技能 store、API 写入、缓冲
    落库的共同汇点）统一过闸；返回原实例，不替换对象、不改内部结构。
    """
    if memoryManager is None:
        return None
    if getattr(memoryManager, ADMISSION_MARKER_ATTR, False):
        return memoryManager
    originalRemember = memoryManager.remember

    def gatedRemember(*args, **kwargs):
        enforceMemoryAdmission(
            _extractRememberContent(args, kwargs),
            origin="memory_manager.remember",
        )
        return originalRemember(*args, **kwargs)

    try:
        memoryManager.remember = gatedRemember
        setattr(memoryManager, ADMISSION_MARKER_ATTR, True)
    except Exception as exc:  # noqa: BLE001 - 只读对象装不上闸时保持原样并留痕
        logger.error("记忆准入闸装配失败（remember 未包层）：%s", exc)
        return memoryManager
    logger.debug("记忆准入闸已装配：remember 写入口已包层")
    return memoryManager
