# -*- coding: utf-8 -*-
"""P2-4 环境上下文 diff 注入（Codex WorldState diff 对齐）。

- 环境段（cwd/模型/平台）在 system 中全量注入（既有行为不变）
- 会话内环境指纹变化时，向当轮上下文追加一条增量提示（"[环境已变化] ..."）；
  未变化零注入——即"后续轮只发增量"语义
"""
from __future__ import annotations

import platform
import threading
from typing import Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def compute_env_fingerprint(workspace_path: str = "", model: str = "") -> Dict[str, str]:
    """环境指纹（参与 diff 的字段集）。"""
    return {
        "workspace": str(workspace_path or ""),
        "model": str(model or ""),
        "platform": platform.system(),
    }


class EnvDeltaTracker:
    """会话级环境指纹台账（单例经 get_env_delta_tracker() 获取）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: Dict[str, Dict[str, str]] = {}

    def note(self, session_id: str, fingerprint: Dict[str, str]) -> Optional[str]:
        """登记当轮指纹；与会话内上轮比对，变化时返回增量提示文本。

        首轮登记返回 None（system 已全量注入，无需重复）。
        """
        sid = str(session_id or "")
        if not sid:
            return None
        with self._lock:
            last = self._last.get(sid)
            self._last[sid] = dict(fingerprint or {})
        if last is None:
            return None
        changed = [
            f"{k}: {last.get(k, '')} → {fingerprint.get(k, '')}"
            for k in sorted(fingerprint or {})
            if str(fingerprint.get(k, "")) != str(last.get(k, ""))
        ]
        if not changed:
            return None
        return "[环境已变化] " + "; ".join(changed)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._last.pop(str(session_id or ""), None)


_TRACKER: Optional[EnvDeltaTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_env_delta_tracker() -> EnvDeltaTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = EnvDeltaTracker()
        return _TRACKER


def reset_env_delta_tracker() -> None:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = None
