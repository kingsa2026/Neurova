"""主动行为引擎（2026-09-15 真实化）

此前 /growth/proactive 与 motivation 依赖的 proactive_behavior_engine 全仓
从未实例化（假接口）。本引擎记录**实际发生的**主动行为并 JSON 落盘：

- 当前真实行为通道=主动提问（post_chat Step 10 弹出问题即记一条）
- 用户对主动提问的回答经 question 队列 answered 回流 → response_received=True
- 行为上限 500（插入序淘汰），重启不丢
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MAX_ACTIONS = 500


class ProactiveBehaviorEngine:
    """主动行为账本（JSON 持久化）。"""

    def __init__(self, agent_id: str, persistence_path: str):
        self.agent_id = str(agent_id)
        self._path = persistence_path
        self._actions: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            actions = payload.get("actions", [])
            if isinstance(actions, list):
                self._actions = [a for a in actions if isinstance(a, dict)]
            logger.info("主动行为账本已加载 %s 条: %s", len(self._actions), self._path)
        except (FileNotFoundError, json.JSONDecodeError):
            return

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"agent_id": self.agent_id, "actions": self._actions}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

    def record_action(
        self,
        action_type: str,
        trigger: str,
        content: str,
        success: bool = True,
    ) -> Dict[str, Any]:
        """记录一条真实发生的主动行为，返回条目 dict。"""
        with self._lock:
            action = {
                "action_id": str(uuid.uuid4()),
                "agent_id": self.agent_id,
                "timestamp": time.time(),
                "action_type": str(action_type),
                "trigger": str(trigger),
                "content": str(content),
                "success": bool(success),
                "response_received": False,
            }
            self._actions.append(action)
            if len(self._actions) > _MAX_ACTIONS:
                self._actions = self._actions[-_MAX_ACTIONS:]
            self._persist()
            return dict(action)

    def get_recent_actions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """按时间倒序返回行为条目（副本）。"""
        with self._lock:
            return [dict(a) for a in reversed(self._actions[-limit:])]

    def mark_response_received(self, action_id: str) -> bool:
        with self._lock:
            for action in self._actions:
                if action.get("action_id") == action_id:
                    action["response_received"] = True
                    self._persist()
                    return True
            return False

    def mark_response_received_by_trigger(self, trigger: str) -> bool:
        """按 trigger 定位（回答回流方无需持有 action_id）。"""
        with self._lock:
            for action in reversed(self._actions):
                if action.get("trigger") == trigger:
                    action["response_received"] = True
                    self._persist()
                    return True
            return False


__all__ = ["ProactiveBehaviorEngine"]
