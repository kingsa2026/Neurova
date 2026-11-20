# -*- coding: utf-8 -*-
"""护栏三招（实施计划项 8）：复核失败即拒 / 跟随式免审 / 车道互斥的前两招。

解决什么问题：computer_use 的动作面里，"只读观察"与"跨站导航/写操作"风险悬殊，
过去一律直通。本模块给导航入口一个统一分类器：

- ``classify(action)`` → ``readonly | follow_nav | sensitive``
  只读白名单直行；``browser_navigate`` 目标与当前页同 registrable domain
  （末两段比对，localhost/127.0.0.1/[::1] 视为同一回环站）**或**是当前页已见
  链接 → follow_nav 免审；其余 sensitive。
- ``review(sensitive)`` → ``allow | deny | unavailable``
  交复核者裁决（默认走仓内 LLM 调用入口 multi_model_client.chat，也可注入
  自定义复核回调）；**复核超时/异常一律返回 unavailable，调用方按拒处理**
  （fail-closed：宁可不做，不可盲目执行）。

回滚开关：环境变量 ``NEUROVA_CUA_GUARDRAIL=off`` 直通（默认开）。
只读白名单默认集保守，可经 ``addReadonlyActions`` / 环境变量
``NEUROVA_CUA_READONLY_EXTRA``（逗号分隔）扩充。

车道互斥（第三招）在 ``lane_mutex.py``，不在本文件。
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Optional
from urllib.parse import urlparse

from neurova.core.logger import get_logger

if TYPE_CHECKING:  # 仅注解用：避免与 browser_manager 的模块级环导入
    from neurova.computer_use.browser_manager import BrowserResult

logger = get_logger(__name__)

__all__ = [
    "Classification",
    "ReviewOutcome",
    "classify",
    "review",
    "sameRegistrableDomain",
    "registrableDomain",
    "guardrailEnabled",
    "setReviewer",
    "resetReviewer",
    "addReadonlyActions",
    "resetReadonlyWhitelist",
    "readonlyWhitelist",
]

#: 分类三档（follow_nav = 跟随式免审：同站或已见链接的导航）
LEVEL_READONLY = "readonly"
LEVEL_FOLLOW_NAV = "follow_nav"
LEVEL_SENSITIVE = "sensitive"

#: 复核裁决三值；unavailable 由超时/异常产生，调用方必须按拒处理
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_UNAVAILABLE = "unavailable"

#: 只读白名单默认集（保守）：观察/滚动/后退/等待类直行。
#: 刻意不含 reload（可能重复提交表单）、press_key、cookies/storage 读取、
#: execute_js、download/print 等有副作用或可外带数据的动作。
DEFAULT_READONLY_ACTIONS = frozenset(
    {
        # 浏览器观察面
        "screenshot",
        "dom_snapshot",
        "dom_read",
        "snapshot",
        "extract_text",
        "extract_links",
        "console_messages",
        "list_targets",
        "get_capabilities",
        # 浏览器无副作用页面动作
        "scroll_by",
        "go_back",
        "wait_for",
        # 桌面观察面
        "computer_screenshot",
        "computer_list_windows",
    }
)

#: 白名单扩充环境变量名（逗号分隔动作名）
READONLY_EXTRA_ENV = "NEUROVA_CUA_READONLY_EXTRA"

#: 复核超时环境变量名与默认值（秒）
REVIEW_TIMEOUT_ENV = "NEUROVA_CUA_REVIEW_TIMEOUT"
DEFAULT_REVIEW_TIMEOUT_SECONDS = 20.0

# 可变白名单（默认集 + 运行期扩充）。进程内共享一份；测试用 resetReadonlyWhitelist 复位。
_readonlyExtra: set[str] = set()

# 注入的复核回调：async (action, params, context) -> "allow"|"deny"|其它
_reviewer: Optional[Callable[..., Any]] = None


def guardrailEnabled() -> bool:
    """护栏总开关（默认开）；``NEUROVA_CUA_GUARDRAIL=off`` 时直通（回滚用）。"""
    return os.environ.get("NEUROVA_CUA_GUARDRAIL", "").strip().lower() != "off"


def reviewTimeoutSeconds() -> float:
    """复核超时秒数（``NEUROVA_CUA_REVIEW_TIMEOUT``，默认 20s）。"""
    raw = os.environ.get(REVIEW_TIMEOUT_ENV, "")
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_REVIEW_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_REVIEW_TIMEOUT_SECONDS


def readonlyWhitelist() -> frozenset:
    """当前生效的只读白名单（默认集 ∪ 运行期扩充 ∪ 环境变量扩充）。"""
    extra_env = {
        name.strip()
        for name in os.environ.get(READONLY_EXTRA_ENV, "").split(",")
        if name.strip()
    }
    return frozenset(DEFAULT_READONLY_ACTIONS | _readonlyExtra | extra_env)


def addReadonlyActions(names: Iterable[str]) -> None:
    """扩充只读白名单（可配置入口；默认集不变，扩充集进程内生效）。"""
    for name in names:
        normalized = str(name or "").strip()
        if normalized:
            _readonlyExtra.add(normalized)


def resetReadonlyWhitelist() -> None:
    """复位扩充集（测试专用；默认集不受影响）。"""
    _readonlyExtra.clear()


# ── 同站判定 ────────────────────────────────────────────────────────

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def registrableDomain(host: str) -> str:
    """取 registrable domain（publicsuffix 兜底口径：末两段）。

    - 回环地址（localhost / 127.0.0.1 / ::1）统一归一为 ``localhost``——
      本机不同端口的服务视为同一站；
    - 纯 IP 主机原样返回（按精确主机比对）；
    - 域名取末两段（如 ``a.b.example.com`` → ``example.com``）。
    """
    host = str(host or "").strip().lower()
    if not host:
        return ""
    if host in _LOOPBACK_HOSTS:
        return "localhost"
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host and host.replace(":", "").replace(".", "").replace("%", "").isalnum():
        # 含冒号且形如 IPv6（无端口语境），按字面比对
        return host
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    return ".".join(labels[-2:])


def sameRegistrableDomain(url_a: str, url_b: str) -> bool:
    """两个 URL 是否同一 registrable domain（末两段比对 + 回环特判）。

    任一 URL 解析不出主机（空串/畸形）→ 不是同站（fail-closed）。
    """
    host_a = urlparse(str(url_a or "")).hostname or ""
    host_b = urlparse(str(url_b or "")).hostname or ""
    if not host_a or not host_b:
        return False
    return registrableDomain(host_a) == registrableDomain(host_b)


# ── 分类 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    """分类结果：level 三档之一，reason/reason_code 供拒绝信息与日志。"""

    level: str
    reason: str
    reason_code: str


def classify(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Classification:
    """动作分类：只读白名单直行；同站/已见链接导航免审；其余 sensitive。

    - action：动作名（browser_* 工具名或 BrowserManager.execute 的裸动作名）；
    - params：动作参数（导航取 ``url``）；
    - context：判定上下文（``currentUrl`` 当前页 URL、``seenLinks`` 已见链接集合）。
    """
    params = params or {}
    context = context or {}
    name = str(action or "").strip()

    if name in readonlyWhitelist():
        return Classification(
            LEVEL_READONLY, "只读白名单动作直行", "readonly_whitelisted"
        )

    if name in ("browser_navigate", "navigate", "open_target"):
        target = str(params.get("url") or "").strip()
        if not target:
            return Classification(
                LEVEL_SENSITIVE, "导航缺少目标 URL，无法判同站", "navigate_missing_url"
            )
        current = str(context.get("currentUrl") or "").strip()
        if current and sameRegistrableDomain(target, current):
            return Classification(
                LEVEL_FOLLOW_NAV,
                f"目标与当前页同站（{registrableDomain(urlparse(target).hostname or '')}）",
                "follow_same_site",
            )
        seen = context.get("seenLinks") or ()
        if target in {str(link or "").strip() for link in seen}:
            return Classification(
                LEVEL_FOLLOW_NAV, "目标是当前页已见链接", "follow_seen_link"
            )
        return Classification(
            LEVEL_SENSITIVE, "跨站导航（非同站且非已见链接）", "cross_site_navigation"
        )

    return Classification(LEVEL_SENSITIVE, "非白名单动作，须复核", "not_whitelisted")


# ── 复核 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReviewOutcome:
    """复核结果：decision 三值之一；unavailable 时调用方按拒处理。"""

    decision: str
    reason: str
    reason_code: str

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW


def setReviewer(reviewer: Optional[Callable[..., Any]]) -> None:
    """注入复核回调：``async (action, params, context) -> "allow"|"deny"|其它``。

    传 None 恢复默认（LLM 复核）。
    """
    global _reviewer
    _reviewer = reviewer


def resetReviewer() -> None:
    """复位注入的复核回调（测试专用）。"""
    global _reviewer
    _reviewer = None


# 复核问询口径：要求复核者只回答 allow/deny 起手词，避免长篇解释拖超时。
_REVIEW_SYSTEM_PROMPT = (
    "你是本地个人智能体的操作安全复核员。用户交给智能体一项任务，"
    "智能体即将执行一个浏览器导航/敏感操作。请判断该操作是否与任务合理相关且风险可接受。"
    "只回答以 allow 或 deny 开头的短句，并给出一行理由。拿不准一律 deny。"
)

_ALLOW_PATTERN = re.compile(r"\ballow\b|\bapprove[d]?\b|\bpermit\b|同意|允许|放行", re.I)
_DENY_PATTERN = re.compile(r"\bdeny\b|\breject(?:ed)?\b|\brefuse[d]?\b|\bblock\b|拒绝|不允许|阻止", re.I)


async def _llmReviewer(
    action: str, params: Dict[str, Any], context: Dict[str, Any]
) -> str:
    """默认复核者：走仓内 LLM 调用入口（multi_model_client.chat）。

    返回 "allow" / "deny"；回答不含判定词时保守按 deny。调用异常向上抛，
    由 review() 归一为 unavailable。
    """
    from neurova.llm.multi_model_client import get_multi_model_client

    target = str(params.get("url") or params or "")
    current = str(context.get("currentUrl") or "")
    user_prompt = (
        f"待复核动作：{action}\n目标：{target}\n当前页：{current or '（未打开页面）'}\n"
        "请裁决 allow 或 deny。"
    )
    messages = [
        {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    result = await get_multi_model_client().chat(messages)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(
            f"LLM 复核不可用：{str((result or {}).get('error') or '无结果')[:200]}"
        )
    answer = str(result.get("response") or "")
    if _ALLOW_PATTERN.search(answer):
        return DECISION_ALLOW
    if _DENY_PATTERN.search(answer):
        return DECISION_DENY
    # 复核者答非所问：按 deny（不给含糊答案放行的口子）
    return DECISION_DENY


async def review(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> ReviewOutcome:
    """敏感动作复核入口：allow / deny / unavailable（超时、异常一律 unavailable）。

    复核者优先级：注入回调（setReviewer）> 默认 LLM 复核。注入回调返回
    非 allow/deny 的值同样按 unavailable 处理（复核面故障不得变成放行）。
    """
    params = params or {}
    context = context or {}
    reviewer = _reviewer or _llmReviewer
    timeout = reviewTimeoutSeconds()
    try:
        outcome = reviewer(action, params, context)
        if asyncio.iscoroutine(outcome):
            outcome = await asyncio.wait_for(outcome, timeout=timeout)
        decision = str(outcome or "").strip().lower()
        if decision == DECISION_ALLOW:
            return ReviewOutcome(DECISION_ALLOW, "复核放行", "review_allowed")
        if decision == DECISION_DENY:
            return ReviewOutcome(DECISION_DENY, "复核拒绝", "review_denied")
        return ReviewOutcome(
            DECISION_UNAVAILABLE,
            f"复核返回不可判定结果：{decision or '（空）'}",
            "reviewer_invalid_result",
        )
    except asyncio.TimeoutError:
        logger.warning("护栏复核超时（%.1fs），按拒处理：%s %s", timeout, action, params)
        return ReviewOutcome(
            DECISION_UNAVAILABLE, f"复核超时（>{timeout:.1f}s）", "reviewer_timeout"
        )
    except Exception as exc:  # noqa: BLE001 - 复核面任何故障都不得放行
        logger.warning("护栏复核异常，按拒处理：%s %s｜%s: %s", action, params, type(exc).__name__, exc)
        return ReviewOutcome(
            DECISION_UNAVAILABLE,
            f"复核不可用：{type(exc).__name__}: {exc}"[:300],
            "reviewer_error",
        )


# ── browser_manager 护栏接缝的自由函数实现（manager 显式传参）──────────
# 方法体放这里、browser_manager 只留 1–3 行委托，是尺寸棘轮（architecture
# baseline 3045）的收口要求；接缝语义见各函数 docstring。

#: 已见链接册容量上限（超出整册老化重收；成员资格判定不受影响）
SEEN_LINKS_CAP = 512


def _seenLinksStore(manager: Any) -> set:
    """取（或懒建）manager 上的已见链接册（状态存 manager，实现在此）。"""
    store = getattr(manager, "_guardrailSeenLinks", None)
    if store is None:
        store = set()
        manager._guardrailSeenLinks = store
    return store


def noteSeenLinks(manager: Any, links: Any) -> None:
    """把当前页出现过的链接入册（follow_nav 免审判据之一）。

    links 兼容两种形态：URL 字符串列表，或 extract_links 的
    ``[{"text": ..., "href": ...}]`` 列表；其它形态静默忽略。
    """
    if not isinstance(links, (list, tuple, set, frozenset)):
        return
    store = _seenLinksStore(manager)
    for link in links:
        if isinstance(link, dict):
            href = link.get("href") or link.get("url") or ""
        else:
            href = link
        href = str(href or "").strip()
        if not href or href in store:
            continue
        if len(store) >= SEEN_LINKS_CAP:
            store.clear()
        store.add(href)


def guardrailSeenLinks(manager: Any) -> frozenset:
    """已见链接册只读视图（护栏判定与观测面用）。"""
    return frozenset(_seenLinksStore(manager))


def currentUrl(manager: Any) -> str:
    """当前活动页 URL（同站判据用；取不到返回空串）。

    三种后端各自记 URL 的位置不同：playwright 在 ``_page.url``、camofox 在
    活动 tab 的 ``url``、scrapling 无页面态——逐个探测，不造第二份事实源。
    """
    backend = getattr(manager, "_active_backend", None)
    if backend is None:
        return ""
    getter = getattr(backend, "currentUrl", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001 - 桩后端/半初始化态按无页处理
            return ""
    page = getattr(backend, "_page", None)
    if page is not None:
        return str(getattr(page, "url", "") or "")
    activeTab = getattr(backend, "_active_tab", None)
    if callable(activeTab):
        try:
            info = activeTab() or {}
            return str(info.get("url") or "")
        except Exception:  # noqa: BLE001
            return ""
    return str(getattr(backend, "_current_url", "") or "")


async def navigationRefusal(manager: Any, url: str) -> Optional["BrowserResult"]:
    """导航护栏：sensitive 且未获复核 allow → 结构化拒绝（**不执行**）。

    返回 None = 放行（只读/跟随式免审，或复核 allow）。拒绝信息带原因码：
    - ``guardrail_denied``：复核明确拒绝；
    - ``guardrail_unavailable``：复核超时/故障（fail-closed，按拒处理）。
    """
    if not guardrailEnabled():
        return None
    context = {
        "currentUrl": currentUrl(manager),
        "seenLinks": _seenLinksStore(manager),
    }
    verdict = classify("browser_navigate", {"url": url}, context)
    if verdict.level != LEVEL_SENSITIVE:
        return None
    outcome = await review("browser_navigate", {"url": url}, context)
    if outcome.allowed:
        return None
    code = (
        "guardrail_denied"
        if outcome.decision == DECISION_DENY
        else "guardrail_unavailable"
    )
    logger.warning("导航被护栏拒绝（%s｜%s）：url=%s", verdict.reason, outcome.reason, url)
    from neurova.computer_use.browser_manager import BrowserResult

    return BrowserResult(
        success=False,
        error=f"导航被护栏拒绝：{verdict.reason}；复核：{outcome.reason}",
        data={
            "guardrail": {
                "code": code,
                "level": verdict.level,
                "reason_code": verdict.reason_code,
                "review_reason_code": outcome.reason_code,
                "url": url,
            }
        },
    )
