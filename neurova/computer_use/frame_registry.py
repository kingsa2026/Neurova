"""桌面观测帧权威（P1-1，电脑操控对照评测）

纪律：模型只对"刚看过的那一帧"下坐标——
- 观测（computer_screenshot / computer_som_snapshot）成功 → 签发新帧，旧帧自动失效；
- 变更动作成功 → 帧失效（画面已变，旧坐标不可信）；
- click / click_mark 携带 frame_id 时校验：非当前帧 → stale_frame 拒绝
  （retry=reobserve，强制先重新观察）。

frame_id 省略 = 既有行为（REST / 用户口述坐标路径不受影响）——严格档由模型
按观测结果里的 frame_id 逐步启用。

会话分键（与 SOM 编号映射同一条会话隔离纪律），有界留存防长期运行无界增长。
本模块是帧事实的**唯一事实源**：不持屏幕元数据第二份（那归 compute_screen_metadata）。
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

_LOCK = threading.RLock()
_latestFrameIds: "OrderedDict[str, str]" = OrderedDict()
_SESSIONS_KEPT = 64

_NO_SESSION = "__no_session__"


def _key(sessionKey: Optional[str]) -> str:
    return sessionKey or _NO_SESSION


def issueFrame(sessionKey: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> str:
    """签发新帧并设为该会话的当前帧（旧帧自动失效）。

    metadata（screen 元数据等）随帧签发留存于审计面，不参与新鲜度判定。
    """
    frameId = f"f-{uuid.uuid4().hex[:12]}"
    key = _key(sessionKey)
    with _LOCK:
        _latestFrameIds[key] = frameId
        _latestFrameIds.move_to_end(key)
        while len(_latestFrameIds) > _SESSIONS_KEPT:
            _latestFrameIds.popitem(last=False)
    return frameId


def invalidateFrame(sessionKey: Optional[str]) -> None:
    """变更动作成功后调用：画面已变，本会话当前帧作废。"""
    with _LOCK:
        _latestFrameIds.pop(_key(sessionKey), None)


def checkFresh(sessionKey: Optional[str], frameId: Optional[str]) -> Tuple[bool, str]:
    """帧新鲜度：等于会话当前帧 → (True, "")；其余（过期/未知/他帧）→ (False, "stale_frame")。"""
    if not frameId:
        return False, "stale_frame"
    with _LOCK:
        latest = _latestFrameIds.get(_key(sessionKey))
    if latest and frameId == latest:
        return True, ""
    return False, "stale_frame"


def latestFrameId(sessionKey: Optional[str]) -> str:
    """当前帧 id（无帧返回空串）——供结果回带与诊断。"""
    with _LOCK:
        return _latestFrameIds.get(_key(sessionKey), "")


def _latestBySession(sessionKey: Optional[str]) -> Optional[str]:
    """测试取数口：返回会话当前帧 id 或 None（超界逐出亦为 None）。"""
    with _LOCK:
        return _latestFrameIds.get(_key(sessionKey))


def resetForTest() -> None:
    """测试隔离：清空全部帧状态（生产勿调）。"""
    with _LOCK:
        _latestFrameIds.clear()


__all__ = [
    "issueFrame",
    "invalidateFrame",
    "checkFresh",
    "latestFrameId",
    "resetForTest",
]
