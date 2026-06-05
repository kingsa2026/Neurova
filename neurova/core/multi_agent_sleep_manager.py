"""Multi-agent sleep manager — per-agent idle tracking, sleep/wake phases, JSON persistence."""

import datetime
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


PHASE_ORDER: List[str] = ["active", "light_sleep", "deep_sleep", "rem", "hibernate"]
PHASE_DISPLAY_NAMES: Dict[str, str] = {
    "active": "Active",
    "light_sleep": "Light Sleep",
    "deep_sleep": "Deep Sleep",
    "rem": "REM Sleep",
    "hibernate": "Hibernate",
}
DEFAULT_TEMPERATURE_THRESHOLDS: Dict[str, float] = {
    "light_sleep": 30.0,
    "deep_sleep": 25.0,
    "rem": 20.0,
    "hibernate": 15.0,
}
DEFAULT_IDLE_THRESHOLDS: Dict[str, int] = {
    "light_sleep": 1800,
    "deep_sleep": 3600,
    "rem": 5400,
    "hibernate": 7200,
}


@dataclass
class SleepConfig:
    sleep_mode: str = "time"
    idle_thresholds: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_IDLE_THRESHOLDS))
    temperature_thresholds: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TEMPERATURE_THRESHOLDS))
    phase_durations: Dict[str, int] = field(default_factory=dict)
    wake_conditions: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sleep_mode": self.sleep_mode,
            "idle_thresholds": dict(self.idle_thresholds),
            "temperature_thresholds": dict(self.temperature_thresholds),
            "phase_durations": dict(self.phase_durations),
            "wake_conditions": dict(self.wake_conditions),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SleepConfig":
        cfg = cls()
        if "sleep_mode" in data:
            cfg.sleep_mode = str(data["sleep_mode"])
        if isinstance(data.get("idle_thresholds"), dict):
            cfg.idle_thresholds = {k: int(v) for k, v in data["idle_thresholds"].items()}
        if isinstance(data.get("temperature_thresholds"), dict):
            cfg.temperature_thresholds = {k: float(v) for k, v in data["temperature_thresholds"].items()}
        if isinstance(data.get("phase_durations"), dict):
            cfg.phase_durations = {k: int(v) for k, v in data["phase_durations"].items()}
        if isinstance(data.get("wake_conditions"), dict):
            cfg.wake_conditions = dict(data["wake_conditions"])
        if "updated_at" in data:
            cfg.updated_at = str(data["updated_at"])
        return cfg


@dataclass
class AgentConfig:
    agent_id: str = ""
    name: str = ""
    sleep_mode: str = "time"
    idle_thresholds: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_IDLE_THRESHOLDS))
    temperature_thresholds: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TEMPERATURE_THRESHOLDS))
    phase_durations: Dict[str, int] = field(default_factory=dict)
    wake_conditions: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "sleep_mode": self.sleep_mode,
            "idle_thresholds": dict(self.idle_thresholds),
            "temperature_thresholds": dict(self.temperature_thresholds),
            "phase_durations": dict(self.phase_durations),
            "wake_conditions": dict(self.wake_conditions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        cfg = cls()
        cfg.agent_id = str(data.get("agent_id", ""))
        cfg.name = str(data.get("name", "")) or cfg.agent_id
        if "sleep_mode" in data:
            cfg.sleep_mode = str(data["sleep_mode"])
        if isinstance(data.get("idle_thresholds"), dict):
            cfg.idle_thresholds = {k: int(v) for k, v in data["idle_thresholds"].items()}
        if isinstance(data.get("temperature_thresholds"), dict):
            cfg.temperature_thresholds = {k: float(v) for k, v in data["temperature_thresholds"].items()}
        if isinstance(data.get("phase_durations"), dict):
            cfg.phase_durations = {k: int(v) for k, v in data["phase_durations"].items()}
        if isinstance(data.get("wake_conditions"), dict):
            cfg.wake_conditions = dict(data["wake_conditions"])
        cfg.created_at = str(data.get("created_at", ""))
        cfg.updated_at = str(data.get("updated_at", ""))
        return cfg

    def to_sleep_config(self) -> SleepConfig:
        return SleepConfig(
            sleep_mode=self.sleep_mode,
            idle_thresholds=dict(self.idle_thresholds),
            temperature_thresholds=dict(self.temperature_thresholds),
            phase_durations=dict(self.phase_durations),
            wake_conditions=dict(self.wake_conditions),
            updated_at=self.updated_at,
        )


class IdleTracker:
    def __init__(
        self,
        agent_id: str,
        sleep_mode: str = "time",
        idle_thresholds: Optional[Dict[str, int]] = None,
        temperature_thresholds: Optional[Dict[str, float]] = None,
        phase_durations: Optional[Dict[str, int]] = None,
        wake_conditions: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.agent_id: str = agent_id
        self._lock = threading.RLock()
        self._current_phase: str = "active"
        self._last_activity_time: float = time.time()
        self._phase_start_time: float = self._last_activity_time
        self._sleep_mode: str = sleep_mode or "time"
        self._idle_thresholds: Dict[str, int] = (
            dict(idle_thresholds) if idle_thresholds else dict(DEFAULT_IDLE_THRESHOLDS)
        )
        self._temperature_thresholds: Dict[str, float] = (
            dict(temperature_thresholds) if temperature_thresholds else dict(DEFAULT_TEMPERATURE_THRESHOLDS)
        )
        self._phase_durations: Dict[str, int] = dict(phase_durations) if phase_durations else {}
        self._wake_conditions: Dict[str, Any] = dict(wake_conditions) if wake_conditions else {}

    def record_activity(self) -> None:
        with self._lock:
            self._current_phase = "active"
            self._last_activity_time = time.time()
            self._phase_start_time = self._last_activity_time

    def get_current_idle_time(self) -> int:
        with self._lock:
            if self._current_phase == "active":
                return int(time.time() - self._last_activity_time)
            return int(time.time() - self._phase_start_time)

    def get_current_phase(self) -> str:
        with self._lock:
            return self._current_phase

    def get_phase_display_name(self, phase: Optional[str] = None) -> str:
        target = phase if phase is not None else self.get_current_phase()
        if not target:
            return ""
        return PHASE_DISPLAY_NAMES.get(target, target.replace("_", " ").title())

    def should_enter_phase(self, target_phase: str, current_temperature: float = 25.0) -> bool:
        with self._lock:
            if target_phase not in PHASE_ORDER or target_phase == "active":
                return False
            if self._sleep_mode == "temperature":
                threshold = self._temperature_thresholds.get(target_phase, 30.0)
                return float(current_temperature) <= threshold
            if self._sleep_mode == "time":
                threshold = int(self._idle_thresholds.get(target_phase, 0))
                return self.get_current_idle_time() >= threshold
            temp_threshold = self._temperature_thresholds.get(target_phase, 30.0)
            time_threshold = int(self._idle_thresholds.get(target_phase, 0))
            return (
                float(current_temperature) <= temp_threshold
                or self.get_current_idle_time() >= time_threshold
            )

    def get_next_phase(self, current_temperature: float = 25.0) -> Optional[str]:
        with self._lock:
            try:
                current_index = PHASE_ORDER.index(self._current_phase)
            except ValueError:
                current_index = 0
            for i in range(current_index + 1, len(PHASE_ORDER)):
                phase = PHASE_ORDER[i]
                if phase == "active":
                    continue
                if self.should_enter_phase(phase, current_temperature):
                    return phase
            return None

    def enter_phase(self, phase: str) -> bool:
        with self._lock:
            if phase not in PHASE_ORDER:
                return False
            if phase == "active":
                self.record_activity()
                return True
            self._current_phase = phase
            self._phase_start_time = time.time()
            return True

    def update_config(
        self,
        sleep_mode: Optional[str] = None,
        idle_thresholds: Optional[Dict[str, int]] = None,
        temperature_thresholds: Optional[Dict[str, float]] = None,
        phase_durations: Optional[Dict[str, int]] = None,
        wake_conditions: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            if sleep_mode is not None:
                self._sleep_mode = sleep_mode
            if idle_thresholds:
                for k, v in idle_thresholds.items():
                    self._idle_thresholds[k] = int(v)
            if temperature_thresholds:
                for k, v in temperature_thresholds.items():
                    self._temperature_thresholds[k] = float(v)
            if phase_durations:
                for k, v in phase_durations.items():
                    self._phase_durations[k] = int(v)
            if wake_conditions:
                for k, v in wake_conditions.items():
                    self._wake_conditions[k] = v

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "current_phase": self._current_phase,
                "current_idle_time": self.get_current_idle_time(),
                "sleep_mode": self._sleep_mode,
            }


class MultiAgentSleepManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config: Dict[str, Any] = config or {}
        storage = self._config.get("storage_dir") or "./data/multi_agent_sleep"
        self._storage_dir: Path = Path(storage)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._agents_path: Path = self._storage_dir / "agents.json"
        self._lock = threading.RLock()
        self._agents: Dict[str, AgentConfig] = {}
        self._trackers: Dict[str, IdleTracker] = {}
        self._module_state: str = "initialized"
        self._load()

    def _on_init(self) -> None:
        with self._lock:
            self._module_state = "initialized"

    def _on_start(self) -> None:
        with self._lock:
            self._module_state = "started"

    def _on_ready(self) -> None:
        with self._lock:
            self._module_state = "ready"

    def _on_stop(self) -> None:
        with self._lock:
            self._module_state = "stopped"

    def _get_agent_json_path(self) -> Path:
        return self._agents_path

    def _read_agent_json(self) -> Dict[str, Any]:
        if not self._agents_path.exists():
            return {}
        try:
            raw = self._agents_path.read_text(encoding="utf-8")
        except Exception:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        if isinstance(data, dict):
            return data
        return {}

    def _write_agent_json(self, data: Dict[str, Any]) -> None:
        try:
            self._agents_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load(self) -> None:
        raw = self._read_agent_json()
        for agent_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            cfg = AgentConfig.from_dict(payload)
            if not cfg.agent_id:
                cfg.agent_id = str(agent_id)
            self._agents[str(agent_id)] = cfg
            self._trackers[str(agent_id)] = self._create_agent_tracker(cfg)

    def _save(self) -> None:
        data: Dict[str, Any] = {aid: cfg.to_dict() for aid, cfg in self._agents.items()}
        self._write_agent_json(data)

    def _normalize_agent_id(self, agent_id: str) -> str:
        return (agent_id or "").strip().lower()

    def _create_agent_tracker(self, agent_cfg: AgentConfig) -> IdleTracker:
        return IdleTracker(
            agent_id=agent_cfg.agent_id or agent_cfg.name,
            sleep_mode=agent_cfg.sleep_mode,
            idle_thresholds=agent_cfg.idle_thresholds,
            temperature_thresholds=agent_cfg.temperature_thresholds,
            phase_durations=agent_cfg.phase_durations,
            wake_conditions=agent_cfg.wake_conditions,
        )

    def register_agent(self, agent_id: str) -> IdleTracker:
        with self._lock:
            key = self._normalize_agent_id(agent_id)
            if not key:
                key = _new_id("agt_")
            existing = self._trackers.get(key)
            if existing is not None:
                return existing
            now = _now_iso()
            cfg = AgentConfig(
                agent_id=key,
                name=key,
                sleep_mode="time",
                idle_thresholds=dict(DEFAULT_IDLE_THRESHOLDS),
                temperature_thresholds=dict(DEFAULT_TEMPERATURE_THRESHOLDS),
                phase_durations={},
                wake_conditions={},
                created_at=now,
                updated_at=now,
            )
            self._agents[key] = cfg
            self._trackers[key] = self._create_agent_tracker(cfg)
            self._save()
            return self._trackers[key]

    def get_agent_tracker(self, agent_id: str) -> Optional[IdleTracker]:
        with self._lock:
            return self._trackers.get(self._normalize_agent_id(agent_id))

    def get_agent_config(self, agent_id: str) -> Optional[SleepConfig]:
        with self._lock:
            cfg = self._agents.get(self._normalize_agent_id(agent_id))
            if cfg is None:
                return None
            return cfg.to_sleep_config()

    def update_agent_config(self, agent_id: str, config: Dict[str, Any]) -> bool:
        if not isinstance(config, dict):
            return False
        with self._lock:
            key = self._normalize_agent_id(agent_id)
            if key not in self._agents:
                self.register_agent(agent_id)
                key = self._normalize_agent_id(agent_id)
            cfg = self._agents[key]
            for k, v in config.items():
                if k == "sleep_mode":
                    cfg.sleep_mode = str(v)
                elif k == "idle_thresholds" and isinstance(v, dict):
                    for ik, iv in v.items():
                        cfg.idle_thresholds[str(ik)] = int(iv)
                elif k == "temperature_thresholds" and isinstance(v, dict):
                    for tk, tv in v.items():
                        cfg.temperature_thresholds[str(tk)] = float(tv)
                elif k == "phase_durations" and isinstance(v, dict):
                    for pk, pv in v.items():
                        cfg.phase_durations[str(pk)] = int(pv)
                elif k == "wake_conditions" and isinstance(v, dict):
                    for wk, wv in v.items():
                        cfg.wake_conditions[str(wk)] = wv
                elif k == "name":
                    cfg.name = str(v)
                else:
                    setattr(cfg, k, v)
            cfg.updated_at = _now_iso()
            tracker = self._trackers.get(key)
            if tracker is not None:
                tracker.update_config(
                    sleep_mode=cfg.sleep_mode,
                    idle_thresholds=cfg.idle_thresholds,
                    temperature_thresholds=cfg.temperature_thresholds,
                    phase_durations=cfg.phase_durations,
                    wake_conditions=cfg.wake_conditions,
                )
            self._save()
            return True

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            key = self._normalize_agent_id(agent_id)
            tracker = self._trackers.get(key)
            cfg = self._agents.get(key)
            if tracker is None or cfg is None:
                return None
            status = tracker.get_status()
            status["config"] = cfg.to_dict()
            return status

    def get_all_agents_status(self) -> List[Dict[str, Any]]:
        with self._lock:
            result: List[Dict[str, Any]] = []
            for key in sorted(self._trackers.keys()):
                status = self.get_agent_status(key)
                if status is not None:
                    result.append(status)
            return result

    def get_registered_agents(self) -> List[str]:
        with self._lock:
            return sorted(self._agents.keys())

    def record_activity(self, agent_id: str) -> bool:
        with self._lock:
            tracker = self._trackers.get(self._normalize_agent_id(agent_id))
            if tracker is None:
                return False
            tracker.record_activity()
            return True

    def enter_phase(self, agent_id: str, phase: str) -> bool:
        with self._lock:
            tracker = self._trackers.get(self._normalize_agent_id(agent_id))
            if tracker is None:
                return False
            return tracker.enter_phase(phase)

    def health_check(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "healthy": True,
                "registered_agents": len(self._agents),
                "module_state": self._module_state,
            }


_singleton: Optional[MultiAgentSleepManager] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/multi_agent_sleep"


def get_multi_agent_sleep_manager() -> MultiAgentSleepManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = MultiAgentSleepManager(config={"storage_dir": _DEFAULT_DIR})
    return _singleton


__all__ = [
    "PHASE_ORDER",
    "PHASE_DISPLAY_NAMES",
    "AgentConfig",
    "IdleTracker",
    "MultiAgentSleepManager",
    "SleepConfig",
    "get_multi_agent_sleep_manager",
]
