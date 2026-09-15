"""动机账本：IntrinsicMotivationSystem 的装配外壳（2026-09-15 真实化）

core/intrinsic_motivation.py 的四驱动模型此前零接线（假接口根因）：
本模块只做三件事——
1. 每 agent 单例（get_motivation_ledger 工厂 + RLock），信号源在 post_chat/
   问题回答回流处 observe_* 灌入真实事件；
2. 跨重启持久化用**事件流回放**：驱动内部状态（skill_level/knowledge_level…）
   无序列化接口，observe 事件 JSON 落盘，重建时重放恢复，不发明第二套状态模型；
3. snapshot() 直接产出 /growth/motivation 端点契约形状（level/factors/drives），
   level=四驱动加权强度，与 drives 自洽，杜绝常量假状态。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.core.intrinsic_motivation import (
    DriveType,
    IntrinsicMotivationSystem,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MAX_EVENTS = 1000


class MotivationLedger:
    """动机账本（事件流持久化 + 真实快照）。"""

    def __init__(self, agent_id: str, persistence_path: str, config: Optional[Dict[str, Any]] = None):
        self.agent_id = str(agent_id)
        self._path = persistence_path
        self._system = IntrinsicMotivationSystem(config)
        self._events: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._updated_at = 0.0
        self._load_and_replay()

    # ── 持久化（事件流回放） ──────────────────────────────────────

    def _load_and_replay(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for ev in payload.get("events", []):
            kind = ev.get("kind")
            if kind == "competence":
                self._apply_competence(ev["success"], ev.get("difficulty", 0.5))
            elif kind == "growth":
                self._apply_growth(ev["concept"], ev.get("understanding", 0.5))
            elif kind == "autonomy":
                self._apply_autonomy(ev["choice"], ev.get("satisfaction", 0.5))
            elif kind == "purpose":
                self._apply_purpose(ev["contribution"], ev.get("impact", 0.5))
            self._events.append(ev)
        weights = payload.get("drive_weights")
        if isinstance(weights, dict):
            parsed = {}
            for k, v in weights.items():
                try:
                    parsed[DriveType(k)] = float(v)
                except (ValueError, TypeError):
                    continue
            if parsed:
                self._system.update_drive_weights(parsed)
        logger.info("动机账本已回放 %s 个事件: %s", len(self._events), self._path)

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        payload = {
            "agent_id": self.agent_id,
            "updated_at": self._updated_at,
            "events": self._events,
            "drive_weights": {dt.value: w for dt, w in self._system.drive_weights.items()},
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

    def _record_event(self, event: Dict[str, Any]) -> None:
        self._events.append(event)
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]
        self._updated_at = time.time()
        self._persist()

    # ── 驱动 apply（无持久化副作用，供 observe 与回放共用） ──────

    def _apply_competence(self, success: bool, difficulty: float) -> None:
        self._system.competence_drive.update_skill_level(success, difficulty)

    def _apply_growth(self, concept: str, understanding: float) -> None:
        self._system.growth_drive.record_learning(concept, understanding)
        self._system.growth_drive.add_curiosity_topic(concept)

    def _apply_autonomy(self, choice: str, satisfaction: float) -> None:
        self._system.autonomy_drive.record_choice(choice, satisfaction)

    def _apply_purpose(self, contribution: str, impact: float) -> None:
        self._system.purpose_drive.record_contribution(contribution, impact)

    # ── 公开 observe 接口（真实信号入口） ────────────────────────

    def observe_competence(self, success: bool, difficulty: float = 0.5) -> None:
        with self._lock:
            self._apply_competence(success, difficulty)
            self._record_event({"kind": "competence", "success": bool(success), "difficulty": float(difficulty)})

    def observe_growth(self, concept: str, understanding: float = 0.5) -> None:
        with self._lock:
            self._apply_growth(concept, understanding)
            self._record_event({"kind": "growth", "concept": str(concept), "understanding": float(understanding)})

    def observe_autonomy(self, choice: str, satisfaction: float = 0.5) -> None:
        with self._lock:
            self._apply_autonomy(choice, satisfaction)
            self._record_event({"kind": "autonomy", "choice": str(choice), "satisfaction": float(satisfaction)})

    def observe_purpose(self, contribution: str, impact: float = 0.5) -> None:
        with self._lock:
            self._apply_purpose(contribution, impact)
            self._record_event({"kind": "purpose", "contribution": str(contribution), "impact": float(impact)})

    def update_drive_weights(self, weights: Dict[str, float]) -> None:
        """全量设置驱动权重（传入键视为完整分布，未传键置 0；自动归一）。"""
        with self._lock:
            parsed = {dt: 0.0 for dt in DriveType}
            for k, v in weights.items():
                try:
                    parsed[DriveType(k)] = max(0.0, float(v))
                except (ValueError, TypeError):
                    raise ValueError(f"非法驱动权重键: {k!r}")
            self._system.update_drive_weights(parsed)
            self._updated_at = time.time()
            self._persist()

    # ── 快照（端点契约） ─────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            drives: Dict[str, Dict[str, float]] = {}
            for dt in DriveType:
                state = self._system.get_drive_state(dt)
                drives[dt.value] = {
                    "intensity": round(state.intensity, 4),
                    "satisfaction": round(state.satisfaction, 4),
                }
            weights = {dt.value: self._system.drive_weights[dt] for dt in DriveType}
            level = round(sum(drives[k]["intensity"] * weights[k] for k in drives), 4)
            return {
                "agent_id": self.agent_id,
                "level": level,
                "factors": [{"name": k, "impact": v["intensity"]} for k, v in drives.items()],
                "drives": drives,
                "drive_weights": weights,
                "event_count": len(self._events),
                "updated_at": self._updated_at or None,
            }


# ── 每 agent 工厂（单例缓存） ────────────────────────────────────

_ledgers: Dict[str, MotivationLedger] = {}
_ledgers_lock = threading.RLock()


def get_motivation_ledger(agent_id: str, workspace_path: str) -> MotivationLedger:
    """按 agent 返回动机账本单例，持久文件 <workspace>/memory/motivation.json。"""
    with _ledgers_lock:
        key = str(agent_id)
        if key not in _ledgers:
            _ledgers[key] = MotivationLedger(
                agent_id=key,
                persistence_path=os.path.join(workspace_path, "memory", "motivation.json"),
            )
        return _ledgers[key]


def reset_motivation_ledgers() -> None:
    """测试/重启用：清空工厂缓存。"""
    with _ledgers_lock:
        _ledgers.clear()


__all__ = ["MotivationLedger", "get_motivation_ledger", "reset_motivation_ledgers"]
