# -*- coding: utf-8 -*-
"""车道互斥（护栏三招之三，实施计划项 8）：desktop 与 browser:<session> 两把容量 1 锁。

解决什么问题：需要前台窗口的桌面动作（pyautogui 输入注入族）与浏览器动作
都会"占据操作面"，并发执行会互踩（浏览器抢焦点/桌面点击落错窗口）。两把
容量 1 的**互斥车道**把这件事变成结构约束：

- ``desktop`` 车道：桌面输入注入族动作（computer_click/type/scroll/key/paste/drag…）；
- ``browser:<session>`` 车道：浏览器动作（按会话/活动 tab 分键）；
- 两侧互斥：desktop 被占时 browser 拒，任一 browser 车道被占时 desktop 拒；
- **unknown 对侧拒绝**：任一侧存在结果未知（unknown）的动作——本地标记或
  ``tool_call_journal`` 同工具 unknown 账目（按请求作用域）——对侧车道直接拒，
  不在未知状态上继续叠加副作用；unknown 收敛（settle）或清除标记后放行。

非阻塞语义：车道被占**立即拒绝**（``LaneRefusal``，code=lane_busy /
lane_unknown），不排队等待——互斥的目的是拒绝而非串行化长动作。

回滚开关：``NEUROVA_CUA_GUARDRAIL=off`` 时 hold() 直通（护栏整体回滚）。
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Optional

from neurova.core.logger import get_logger

if TYPE_CHECKING:  # 仅注解用：避免与 browser_manager 的模块级环导入
    from neurova.computer_use.browser_manager import BrowserResult

logger = get_logger(__name__)

__all__ = [
    "LaneMutex",
    "LaneRefusal",
    "DESKTOP_LANE",
    "BROWSER_LANE_PREFIX",
    "DESKTOP_LANE_TOOLS",
    "BROWSER_LANE_TOOLS",
    "get_lane_mutex",
    "reset_lane_mutex",
    "currentLaneScope",
    "activeSessionKey",
    "runNavigation",
    "runOpenTarget",
]

#: 桌面车道键（前台输入注入族）
DESKTOP_LANE = "desktop"
#: 浏览器车道键前缀（完整键 = browser:<session 或 target>）
BROWSER_LANE_PREFIX = "browser:"

#: 桌面车道涉及的工具（journal unknown 判据；与 FOREGROUND_DESKTOP_TOOLS 同口径，
#: 因包 __init__ 与本模块有懒加载链，这里按名单抄录并在测试里对账）
DESKTOP_LANE_TOOLS = frozenset(
    {
        "computer_click",
        "computer_type",
        "computer_scroll",
        "computer_key",
        "computer_paste",
        "computer_drag",
        "computer_click_element",
        "computer_set_value",
        "computer_click_mark",
    }
)

#: 浏览器车道涉及的工具（有副作用/会改变页面事实的一族；只读观察不占车道）
BROWSER_LANE_TOOLS = frozenset(
    {
        "browser_navigate",
        "browser_open_target",
        "browser_click",
        "browser_type",
        "browser_execute_js",
        "browser_download",
        "browser_upload",
        "browser_install",
    }
)


class LaneRefusal(Exception):
    """车道拒绝：code=lane_busy（被占）/ lane_unknown（对侧存在未知结果）。"""

    def __init__(self, code: str, lane: str, message: str):
        super().__init__(message)
        self.code = code
        self.lane = lane
        self.message = message


def currentLaneScope() -> str:
    """当前请求作用域（``<request_user_id>:<session_id>``），journal 判据用它。"""
    user = "anonymous"
    try:
        from neurova.core.identity_context import get_request_user_id

        user = get_request_user_id() or "anonymous"
    except Exception:  # noqa: BLE001 - 身份上下文不可用时按匿名判（不阻断车道判定）
        pass
    session = ""
    try:
        from neurova.core.turn_context import get_turn_session_id

        session = get_turn_session_id() or ""
    except Exception:  # noqa: BLE001
        pass
    return f"{user}:{session}"


class LaneMutex:
    """两把容量 1 的互斥车道（desktop / browser:<session>），进程内共享。"""

    def __init__(self):
        self._lock = threading.RLock()
        # lane 键 → 持有者 token
        self._held: dict[str, str] = {}
        # 本地 unknown 标记（lane 键集合；journal unknown 之外的补充判据）
        self._unknown: set[str] = set()

    # ── 判定 ────────────────────────────────────────────────────────

    @staticmethod
    def _isBrowserLane(lane: str) -> bool:
        return str(lane).startswith(BROWSER_LANE_PREFIX)

    def _oppositeUnknown(self, lane: str, scope: str) -> Optional[str]:
        """对侧是否存在 unknown（本地标记优先，journal 同工具账目兜底）。

        返回 None = 无 unknown；否则返回具名原因。journal 读失败按"无信息"
        处理（本地标记仍然生效）——journal 是只读参考信号，硬拒绝由本地
        标记与占用判定承担。
        """
        if self._isBrowserLane(lane):
            opposite = DESKTOP_LANE
            oppositeTools = DESKTOP_LANE_TOOLS
        else:
            opposite = None  # 对侧是任意 browser 车道
            oppositeTools = BROWSER_LANE_TOOLS
        with self._lock:
            if opposite is not None:
                if opposite in self._unknown:
                    return f"{opposite} 车道存在结果未知的动作（本地标记）"
            else:
                for key in self._unknown:
                    if self._isBrowserLane(key):
                        return f"{key} 车道存在结果未知的动作（本地标记）"
        try:
            from neurova.core.tool_call_journal import get_tool_call_journal

            if get_tool_call_journal().hasUnknown(tool_names=oppositeTools, scope=scope):
                return (
                    f"{'桌面' if opposite is not None else '浏览器'}车道存在"
                    f" unknown 账目（journal，scope={scope or '当前'}）"
                )
        except Exception as exc:  # noqa: BLE001 - journal 不可用不阻断（见上）
            logger.debug("车道 unknown 判据读 journal 失败（按无信息处理）: %s", exc)
        return None

    def _tryAcquire(self, lane: str, scope: str, owner: str) -> str:
        if not str(lane).startswith(BROWSER_LANE_PREFIX) and lane != DESKTOP_LANE:
            raise ValueError(f"未知车道：{lane!r}（合法：desktop / browser:<session>）")
        with self._lock:
            unknownReason = self._oppositeUnknown(lane, scope)
            if unknownReason:
                raise LaneRefusal(
                    "lane_unknown", lane, f"拒绝进入 {lane} 车道：{unknownReason}"
                )
            if lane in self._held:
                raise LaneRefusal(
                    "lane_busy", lane, f"{lane} 车道正被 {self._held[lane]} 占用"
                )
            if lane == DESKTOP_LANE:
                browserHeld = [key for key in self._held if self._isBrowserLane(key)]
                if browserHeld:
                    raise LaneRefusal(
                        "lane_busy",
                        lane,
                        f"桌面车道与浏览器车道互斥：{','.join(sorted(browserHeld))} 正在执行",
                    )
            else:
                if DESKTOP_LANE in self._held:
                    raise LaneRefusal(
                        "lane_busy",
                        lane,
                        f"浏览器车道与桌面车道互斥：desktop 正在执行",
                    )
            self._held[lane] = owner
            return owner

    def _release(self, lane: str, owner: str) -> None:
        with self._lock:
            if self._held.get(lane) == owner:
                del self._held[lane]

    @contextmanager
    def hold(self, lane: str, scope: str = "", owner: str = "") -> Iterator[str]:
        """占用车道（非阻塞）：拒绝抛 LaneRefusal；护栏关闭时直通。

        - lane：``desktop`` 或 ``browser:<session>``；
        - scope：journal unknown 判据的作用域（缺省取当前请求作用域）；
        - owner：持有者标识（缺省自动生成，用于日志与排他）。
        """
        from neurova.computer_use.guardrail import guardrailEnabled

        token = owner or f"{lane}#{uuid.uuid4().hex[:8]}"
        if not guardrailEnabled():
            yield token
            return
        effectiveScope = scope if scope is not None else currentLaneScope()
        self._tryAcquire(lane, effectiveScope, token)
        try:
            yield token
        finally:
            self._release(lane, token)

    # ── unknown 本地标记 ────────────────────────────────────────────

    def markUnknown(self, lane: str) -> None:
        """标记某车道刚发生过结果未知的动作（对侧车道随即拒绝）。"""
        with self._lock:
            self._unknown.add(lane)

    def clearUnknown(self, lane: str) -> None:
        """清除 unknown 标记（结果已确认/已处置）。"""
        with self._lock:
            self._unknown.discard(lane)

    def isUnknown(self, lane: str) -> bool:
        with self._lock:
            return lane in self._unknown


# ── 进程级单例（DCL + RLock，仓规） ──────────────────────────────────

_mutexInstance: Optional[LaneMutex] = None
_mutexLock = threading.RLock()


def get_lane_mutex() -> LaneMutex:
    global _mutexInstance
    if _mutexInstance is None:
        with _mutexLock:
            if _mutexInstance is None:
                _mutexInstance = LaneMutex()
    return _mutexInstance


def reset_lane_mutex() -> None:
    """重置单例（测试专用）。"""
    global _mutexInstance
    with _mutexLock:
        _mutexInstance = None


# ── browser_manager 车道接缝的自由函数实现（manager 显式传参）──────────
# 方法体放这里、browser_manager 只留 1–3 行委托，是尺寸棘轮（architecture
# baseline 3045）的收口要求；接缝语义见各函数 docstring。


def activeSessionKey(manager: Any) -> str:
    """浏览器车道键的属主+会话段（属主在前，活动 tab 在后）。

    属主段（``user:*`` / ``agent:*`` / ``default``，单源
    ``resolveBrowserOwnerKey``）让不同用户的浏览器动作各占各的车道，互不占锁；
    同属主内仍按活动 tab 细分。desktop 与任一 ``browser:*`` 车道保持互斥不变。
    """
    from neurova.computer_use.browser_manager import resolveBrowserOwnerKey

    backend = getattr(manager, "_active_backend", None)
    target = getattr(backend, "_active_target_id", None)
    return f"{resolveBrowserOwnerKey()}:{target or 'default'}"


async def runNavigation(manager: Any, url: str, backend: Any, generation: Any) -> "BrowserResult":
    """浏览器导航的车道包装：先过护栏复核，再持 browser:<session> 车道执行。

    - 护栏拒（sensitive 未获 allow / 复核不可用）→ 结构化拒绝，不执行；
    - 车道被拒（desktop 正忙或对侧存在 unknown）→ 结构化拒绝，不执行；
    - 成功后把目标 URL 记入已见链接册（后续同站/已见链接免审判据）。
    """
    from neurova.computer_use import guardrail

    refusal = await guardrail.navigationRefusal(manager, url)
    if refusal is not None:
        return refusal
    laneKey = f"{BROWSER_LANE_PREFIX}{activeSessionKey(manager)}"
    try:
        with get_lane_mutex().hold(laneKey, scope=currentLaneScope()):
            b = await manager._get_backend(backend)
            result = await b.navigate(url, generation)
    except LaneRefusal as laneRefusal:
        # 车道互斥拒绝：结构化返回，不执行导航（对侧车道可能正持前台）
        logger.warning("导航被车道拒绝（%s）：%s", laneRefusal.code, laneRefusal.message)
        from neurova.computer_use.browser_manager import BrowserResult

        return BrowserResult(
            success=False,
            error=laneRefusal.message,
            data={
                "guardrail": {
                    "code": laneRefusal.code,
                    "lane": laneRefusal.lane,
                    "url": url,
                }
            },
        )
    if result.success:
        guardrail.noteSeenLinks(manager, [url])
    return result


async def runOpenTarget(manager: Any, url: Optional[str], backend: Any) -> "BrowserResult":
    """新标签（open_target）的车道包装：与 `runNavigation` 同一护栏与车道。

    新开 tab 会激活并占据操作面，等价于一次导航：URL 非空必须先过
    `navigationRefusal`（CORE-17——原实现直调后端，可带任意 URL 绕过复核），
    执行必须持 browser:<session> 车道（与 desktop 互斥）。成功且 URL 非空时
    记入已见链接册，后续同站/已见链接免审判据与 navigate 一致。
    """
    from neurova.computer_use import guardrail

    if url:
        refusal = await guardrail.navigationRefusal(manager, url)
        if refusal is not None:
            return refusal
    laneKey = f"{BROWSER_LANE_PREFIX}{activeSessionKey(manager)}"
    try:
        with get_lane_mutex().hold(laneKey, scope=currentLaneScope()):
            b = await manager._get_backend(backend)
            result = await b.open_target(url)
    except LaneRefusal as laneRefusal:
        logger.warning("新标签被车道拒绝（%s）：%s", laneRefusal.code, laneRefusal.message)
        from neurova.computer_use.browser_manager import BrowserResult

        return BrowserResult(
            success=False,
            error=laneRefusal.message,
            data={
                "guardrail": {
                    "code": laneRefusal.code,
                    "lane": laneRefusal.lane,
                    "url": url,
                }
            },
        )
    if result.success and url:
        guardrail.noteSeenLinks(manager, [url])
    return result
