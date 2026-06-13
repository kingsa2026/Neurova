from __future__ import annotations

"""
个性发展系统

基于OCEAN模型的个性特征追踪和发展系统
- Openness (开放性): 对新体验的开放程度
- Conscientiousness (尽责性): 组织性和责任感
- Extraversion (外向性): 社交能量水平
- Agreeableness (宜人性): 合作性和同理心
- Neuroticism (神经质): 情绪稳定性
"""

import datetime
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.base_module import BaseModule, ModuleState

logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class PersonalityTrait(str, Enum):
    """个性特征（基于 OCEAN 模型）"""

    OPENNESS = "openness"
    CONSCIENTIOUSNESS = "conscientiousness"
    EXTRAVERSION = "extraversion"
    AGREEABLENESS = "agreeableness"
    NEUROTICISM = "neuroticism"


_TRAIT_NAMES_CN: Dict[PersonalityTrait, str] = {
    PersonalityTrait.OPENNESS: "开放性",
    PersonalityTrait.CONSCIENTIOUSNESS: "尽责性",
    PersonalityTrait.EXTRAVERSION: "外向性",
    PersonalityTrait.AGREEABLENESS: "宜人性",
    PersonalityTrait.NEUROTICISM: "神经质",
}

_DEFAULT_TRAIT_VALUE: float = 0.5


@dataclass
class TraitRecord:
    """特征记录"""

    trait: PersonalityTrait
    value: float
    confidence: float = 0.0
    sample_size: int = 0
    last_updated: datetime.datetime = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.last_updated is None:
            self.last_updated = datetime.datetime.now()
        if self.history is None:
            self.history = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trait": self.trait.value,
            "value": float(self.value),
            "confidence": float(self.confidence),
            "sample_size": int(self.sample_size),
            "last_updated": self.last_updated.isoformat(),
            "history": list(self.history),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraitRecord":
        ts_raw = data.get("last_updated")
        ts: Optional[datetime.datetime] = None
        if ts_raw:
            try:
                ts = datetime.datetime.fromisoformat(ts_raw)
            except (TypeError, ValueError):
                ts = None
        return cls(
            trait=PersonalityTrait(data["trait"]),
            value=float(data["value"]),
            confidence=float(data.get("confidence", 0.0)),
            sample_size=int(data.get("sample_size", 0)),
            last_updated=ts,
            history=list(data.get("history", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class Experience:
    """经验"""

    experience_id: str
    description: str
    impact_score: float = 0.0
    traits_affected: List[PersonalityTrait] = field(default_factory=list)
    trait_impacts: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime.datetime = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.traits_affected is None:
            self.traits_affected = []
        if self.trait_impacts is None:
            self.trait_impacts = {}
        if self.timestamp is None:
            self.timestamp = datetime.datetime.now()
        if self.context is None:
            self.context = {}
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "description": self.description,
            "impact_score": float(self.impact_score),
            "traits_affected": [t.value for t in self.traits_affected],
            "trait_impacts": dict(self.trait_impacts),
            "timestamp": self.timestamp.isoformat(),
            "context": dict(self.context),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experience":
        ts_raw = data.get("timestamp")
        ts: Optional[datetime.datetime] = None
        if ts_raw:
            try:
                ts = datetime.datetime.fromisoformat(ts_raw)
            except (TypeError, ValueError):
                ts = None
        return cls(
            experience_id=data["experience_id"],
            description=data["description"],
            impact_score=float(data.get("impact_score", 0.0)),
            traits_affected=[PersonalityTrait(t) for t in data.get("traits_affected", [])],
            trait_impacts=dict(data.get("trait_impacts", {})),
            timestamp=ts,
            context=dict(data.get("context", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class PersonalitySnapshot:
    """个性快照"""

    snapshot_id: str
    timestamp: datetime.datetime
    traits: Dict[PersonalityTrait, float] = field(default_factory=dict)
    confidence_scores: Dict[PersonalityTrait, float] = field(default_factory=dict)
    sample_sizes: Dict[PersonalityTrait, int] = field(default_factory=dict)
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.traits is None:
            self.traits = {}
        if self.confidence_scores is None:
            self.confidence_scores = {}
        if self.sample_sizes is None:
            self.sample_sizes = {}
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "traits": {t.value: float(v) for t, v in self.traits.items()},
            "confidence_scores": {t.value: float(v) for t, v in self.confidence_scores.items()},
            "sample_sizes": {t.value: int(v) for t, v in self.sample_sizes.items()},
            "label": self.label,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalitySnapshot":
        ts_raw = data.get("timestamp")
        ts: Optional[datetime.datetime] = None
        if ts_raw:
            try:
                ts = datetime.datetime.fromisoformat(ts_raw)
            except (TypeError, ValueError):
                ts = None
        if ts is None:
            ts = datetime.datetime.now()
        return cls(
            snapshot_id=data["snapshot_id"],
            timestamp=ts,
            traits={PersonalityTrait(k): float(v) for k, v in data.get("traits", {}).items()},
            confidence_scores={PersonalityTrait(k): float(v) for k, v in data.get("confidence_scores", {}).items()},
            sample_sizes={PersonalityTrait(k): int(v) for k, v in data.get("sample_sizes", {}).items()},
            label=data.get("label", ""),
            metadata=dict(data.get("metadata", {})),
        )


class PersonalityDevelopmentSystem(BaseModule):
    MODULE_ID = "personality_development_system"
    MODULE_NAME = "Personality Development System"
    MODULE_VERSION = "1.0.0"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Any = None,
        storage_dir: Optional[str] = None,
        initial_traits: Optional[Dict[PersonalityTrait, float]] = None,
        drift_learning_rate: float = 0.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            config=config or {},
            event_bus=event_bus,
            module_id=self.MODULE_ID,
            name=self.MODULE_NAME,
            version=self.MODULE_VERSION,
            **kwargs,
        )
        self._drift_learning_rate: float = max(0.0, min(1.0, float(drift_learning_rate)))
        self._traits: Dict[PersonalityTrait, TraitRecord] = {}
        self._experiences: Dict[str, Experience] = {}
        self._snapshots: Dict[str, PersonalitySnapshot] = {}
        self._insights: List[Dict[str, Any]] = []
        self._mood: Dict[str, Any] = {
            "valence": _DEFAULT_TRAIT_VALUE,
            "arousal": _DEFAULT_TRAIT_VALUE,
            "label": "neutral",
            "updated_at": _now_iso(),
        }
        self._mood_history: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

        self._init_default_traits(initial_traits or {})

        if storage_dir:
            self._dir = Path(storage_dir)
            self._dir.mkdir(parents=True, exist_ok=True)
            self._state_path = self._dir / "personality_state.json"
            self._traits_path = self._dir / "traits.json"
            self._experiences_path = self._dir / "experiences.json"
            self._snapshots_path = self._dir / "snapshots.json"
            self._mood_path = self._dir / "mood.json"
        else:
            self._dir = None
            self._state_path = None
            self._traits_path = None
            self._experiences_path = None
            self._snapshots_path = None
            self._mood_path = None

        if self._dir is not None:
            self._load_from_state()
            self._save_state()
            self._save_traits()
            self._save_experiences()
            self._save_snapshots()
            self._save_mood()

    def on_initialize(self) -> None:
        self.set_state(ModuleState.INITIALIZING)
        if not self._traits:
            self._init_default_traits({})
        if self._dir is not None:
            self._load_from_state()
        self.set_state(ModuleState.INITIALIZED)

    def on_start(self) -> None:
        self.set_state(ModuleState.RUNNING)

    def on_stop(self) -> None:
        self.set_state(ModuleState.STOPPED)

    def _init_default_traits(self, overrides: Dict[PersonalityTrait, float]) -> None:
        with self._lock:
            for trait in PersonalityTrait:
                initial = overrides.get(trait, _DEFAULT_TRAIT_VALUE)
                rec = TraitRecord(
                    trait=trait,
                    value=max(0.0, min(1.0, float(initial))),
                )
                self._traits[trait] = rec

    def _on_experience_recorded(self, experience: Experience) -> None:
        if self._dir is not None:
            self._save_experiences()
        self.emit_event(
            "personality.experience_recorded",
            experience.to_dict(),
        )

    def _on_analyze_request(self, payload: Dict[str, Any]) -> None:
        self.emit_event("personality.analyze_requested", payload or {})

    def record_experience(
        self,
        description: str,
        impact_score: float = 0.5,
        traits_affected: Optional[List[PersonalityTrait]] = None,
        trait_impacts: Optional[Dict[str, float]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            impact = max(0.0, min(1.0, float(impact_score)))
            traits_list: List[PersonalityTrait] = list(traits_affected) if traits_affected else []
            impacts_map: Dict[str, float] = dict(trait_impacts) if trait_impacts else {}
            if not traits_list and impacts_map:
                for key in impacts_map.keys():
                    try:
                        traits_list.append(PersonalityTrait(key))
                    except ValueError:
                        continue
            eid = _new_id("exp_")
            exp = Experience(
                experience_id=eid,
                description=description or "",
                impact_score=impact,
                traits_affected=traits_list,
                trait_impacts=impacts_map,
                context=dict(context) if context else {},
            )
            self._experiences[eid] = exp
            self._apply_trait_changes(exp)
            insight = self._generate_insight(exp)
            if insight:
                self._insights.append(insight)
            self._on_experience_recorded(exp)
            return eid

    def _calculate_impact_score(self, impact: float, sample_size: int) -> float:
        n = max(1, int(sample_size))
        return max(0.0, min(1.0, float(impact) * (1.0 - 1.0 / (n + 1))))

    def _analyze_impact(self, experience: Experience) -> Dict[str, Any]:
        affected = [t.value for t in experience.traits_affected]
        impacts = dict(experience.trait_impacts)
        return {
            "experience_id": experience.experience_id,
            "impact_score": experience.impact_score,
            "traits_affected": affected,
            "trait_impacts": impacts,
            "summary": f"{experience.description} -> {', '.join(affected) or 'none'}",
        }

    def _calculate_trait_change(
        self,
        trait: PersonalityTrait,
        impact: float,
        current_value: float,
    ) -> float:
        sign = 1.0 if impact >= 0 else -1.0
        magnitude = abs(impact) * self._drift_learning_rate
        return sign * magnitude

    def _apply_trait_changes(self, experience: Experience) -> None:
        if not experience.traits_affected:
            return
        for trait in experience.traits_affected:
            impact = float(experience.trait_impacts.get(trait.value, 0.0))
            if impact == 0.0:
                impact = experience.impact_score * 0.05
            rec = self._traits.get(trait)
            if rec is None:
                rec = TraitRecord(trait=trait, value=_DEFAULT_TRAIT_VALUE)
                self._traits[trait] = rec
            delta = self._calculate_trait_change(trait, impact, rec.value)
            new_value = max(0.0, min(1.0, rec.value + delta))
            rec.value = new_value
            rec.sample_size += 1
            rec.confidence = min(1.0, rec.confidence + 0.02)
            rec.last_updated = datetime.datetime.now()
            rec.history.append(
                {
                    "ts": _now_iso(),
                    "value": float(new_value),
                    "delta": float(delta),
                    "experience_id": experience.experience_id,
                    "source": "experience",
                }
            )
            if len(rec.history) > 200:
                rec.history = rec.history[-200:]

    def _generate_insight(self, experience: Experience) -> Optional[Dict[str, Any]]:
        if not experience.traits_affected:
            return None
        affected = [t.value for t in experience.traits_affected]
        description = (
            f"Experience '{experience.description}' impacted "
            f"{', '.join(affected)} (impact={experience.impact_score:.2f})"
        )
        return {
            "insight_id": _new_id("ins_"),
            "experience_id": experience.experience_id,
            "description": description,
            "affected_traits": affected,
            "impact_score": experience.impact_score,
            "created_at": _now_iso(),
        }

    def _get_trait_name(self, trait: PersonalityTrait) -> str:
        return _TRAIT_NAMES_CN.get(trait, trait.value)

    def update_trait(
        self,
        trait: PersonalityTrait,
        value: float = 0.5,
        confidence: float = 0.0,
    ) -> bool:
        with self._lock:
            rec = self._traits.get(trait)
            if rec is None:
                rec = TraitRecord(trait=trait, value=_DEFAULT_TRAIT_VALUE)
                self._traits[trait] = rec
            new_value = max(0.0, min(1.0, float(value)))
            old_value = rec.value
            rec.value = new_value
            rec.confidence = max(0.0, min(1.0, float(confidence)))
            rec.sample_size += 1
            rec.last_updated = datetime.datetime.now()
            rec.history.append(
                {
                    "ts": _now_iso(),
                    "value": float(new_value),
                    "old_value": float(old_value),
                    "delta": float(new_value - old_value),
                    "source": "update_trait",
                }
            )
            if len(rec.history) > 200:
                rec.history = rec.history[-200:]
            if self._dir is not None:
                self._save_traits()
            self.emit_event(
                "personality.trait_updated",
                {"trait": trait.value, "value": rec.value, "confidence": rec.confidence},
            )
            return True

    def get_trait(self, trait: PersonalityTrait) -> Optional[TraitRecord]:
        with self._lock:
            rec = self._traits.get(trait)
            return rec if rec else None

    def get_current_traits(self) -> Dict[PersonalityTrait, float]:
        with self._lock:
            return {t: float(r.value) for t, r in self._traits.items()}

    def get_dominant_trait(self) -> Dict[str, Any]:
        with self._lock:
            if not self._traits:
                return {"trait": "", "value": 0.0, "name": ""}
            dom_trait, dom_rec = max(
                self._traits.items(),
                key=lambda kv: (float(kv[1].value), float(kv[1].confidence)),
            )
            return {
                "trait": dom_trait.value,
                "value": float(dom_rec.value),
                "confidence": float(dom_rec.confidence),
                "name": self._get_trait_name(dom_trait),
            }

    def get_trait_history(self, trait: PersonalityTrait) -> List[Dict[str, Any]]:
        with self._lock:
            rec = self._traits.get(trait)
            return list(rec.history) if rec else []

    def get_experiences(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._experiences.values()]

    def get_personality_snapshot(self) -> PersonalitySnapshot:
        with self._lock:
            traits_map: Dict[PersonalityTrait, float] = {}
            conf_map: Dict[PersonalityTrait, float] = {}
            sample_map: Dict[PersonalityTrait, int] = {}
            for t, rec in self._traits.items():
                traits_map[t] = float(rec.value)
                conf_map[t] = float(rec.confidence)
                sample_map[t] = int(rec.sample_size)
            snap = PersonalitySnapshot(
                snapshot_id=_new_id("snap_"),
                timestamp=datetime.datetime.now(),
                traits=traits_map,
                confidence_scores=conf_map,
                sample_sizes=sample_map,
            )
            return snap

    def take_snapshot(self, label: str = "") -> str:
        with self._lock:
            snap = self.get_personality_snapshot()
            snap.label = label or ""
            self._snapshots[snap.snapshot_id] = snap
            if self._dir is not None:
                self._save_snapshots()
            self.emit_event("personality.snapshot_taken", snap.to_dict())
            return snap.snapshot_id

    def get_snapshot_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = [s.to_dict() for s in self._snapshots.values()]
            items.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
            return items

    def _calculate_stability(self) -> float:
        if not self._traits:
            return 0.0
        history_lengths = [len(r.history) for r in self._traits.values()]
        total_samples = sum(history_lengths)
        if total_samples == 0:
            return 1.0
        deltas: List[float] = []
        for r in self._traits.values():
            for entry in r.history:
                delta = abs(float(entry.get("delta", 0.0)))
                deltas.append(delta)
        if not deltas:
            return 1.0
        mean_abs_delta = sum(deltas) / len(deltas)
        stability = max(0.0, min(1.0, 1.0 - mean_abs_delta * 4.0))
        return stability

    def get_stability(self) -> float:
        with self._lock:
            return self._calculate_stability()

    def get_insights(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._insights)

    def get_development_report(self) -> Dict[str, Any]:
        with self._lock:
            trends = self._analyze_development_trend()
            dominant = self.get_dominant_trait()
            stability = self._calculate_stability()
            return {
                "module_id": self.MODULE_ID,
                "module_version": self.MODULE_VERSION,
                "generated_at": _now_iso(),
                "traits": {t.value: float(r.value) for t, r in self._traits.items()},
                "confidence_scores": {t.value: float(r.confidence) for t, r in self._traits.items()},
                "sample_sizes": {t.value: int(r.sample_size) for t, r in self._traits.items()},
                "dominant_trait": dominant,
                "stability": round(stability, 3),
                "total_experiences": len(self._experiences),
                "total_snapshots": len(self._snapshots),
                "total_insights": len(self._insights),
                "trends": trends,
                "mood": dict(self._mood),
            }

    def _analyze_development_trend(self) -> Dict[str, Any]:
        trends: Dict[str, str] = {}
        deltas: Dict[str, float] = {}
        for trait, rec in self._traits.items():
            if len(rec.history) < 2:
                trends[trait.value] = "stable"
                deltas[trait.value] = 0.0
                continue
            first_val = float(rec.history[0].get("value", rec.value))
            last_val = float(rec.history[-1].get("value", rec.value))
            diff = last_val - first_val
            deltas[trait.value] = round(diff, 4)
            if abs(diff) < 0.01:
                trends[trait.value] = "stable"
            elif diff > 0:
                trends[trait.value] = "increasing"
            else:
                trends[trait.value] = "decreasing"
        return {"directions": trends, "deltas": deltas}

    def consistency_check(
        self,
        snapshot_id: Optional[str] = None,
        threshold: float = 0.05,
    ) -> Dict[str, Any]:
        with self._lock:
            if snapshot_id is not None:
                snap = self._snapshots.get(snapshot_id)
                if snap is None:
                    return {
                        "consistent": False,
                        "error": "snapshot_not_found",
                        "snapshot_id": snapshot_id,
                        "drifted_traits": {},
                        "max_drift": 0.0,
                        "threshold": float(threshold),
                    }
            else:
                snaps = sorted(
                    self._snapshots.values(),
                    key=lambda s: s.timestamp,
                    reverse=True,
                )
                if not snaps:
                    snap = self.get_personality_snapshot()
                else:
                    snap = snaps[0]
            drifted: Dict[str, float] = {}
            max_drift = 0.0
            for trait, base_value in snap.traits.items():
                rec = self._traits.get(trait)
                if rec is None:
                    continue
                current = float(rec.value)
                base = float(base_value)
                diff = abs(current - base)
                if diff > float(threshold):
                    drifted[trait.value] = round(current - base, 4)
                if diff > max_drift:
                    max_drift = diff
            return {
                "consistent": len(drifted) == 0,
                "snapshot_id": snap.snapshot_id,
                "threshold": float(threshold),
                "max_drift": round(max_drift, 4),
                "drifted_traits": drifted,
                "checked_at": _now_iso(),
            }

    def drift_trait(
        self,
        trait: PersonalityTrait,
        delta: float = 0.05,
        steps: int = 1,
    ) -> Dict[str, Any]:
        with self._lock:
            n = max(1, int(steps))
            d = float(delta) / n
            rec = self._traits.get(trait)
            if rec is None:
                rec = TraitRecord(trait=trait, value=_DEFAULT_TRAIT_VALUE)
                self._traits[trait] = rec
            applied: List[float] = []
            for _ in range(n):
                new_value = max(0.0, min(1.0, rec.value + d))
                applied.append(float(new_value))
                rec.value = new_value
                rec.last_updated = datetime.datetime.now()
                rec.history.append(
                    {
                        "ts": _now_iso(),
                        "value": float(new_value),
                        "delta": float(d),
                        "source": "drift_trait",
                    }
                )
            if len(rec.history) > 200:
                rec.history = rec.history[-200:]
            if self._dir is not None:
                self._save_traits()
            return {
                "trait": trait.value,
                "delta_per_step": d,
                "steps": n,
                "final_value": float(rec.value),
                "applied_values": applied,
            }

    def set_mood(
        self,
        valence: float = 0.5,
        arousal: float = 0.5,
        label: str = "neutral",
    ) -> bool:
        with self._lock:
            v = max(0.0, min(1.0, float(valence)))
            a = max(0.0, min(1.0, float(arousal)))
            self._mood = {
                "valence": v,
                "arousal": a,
                "label": str(label) if label else "neutral",
                "updated_at": _now_iso(),
            }
            self._mood_history.append(dict(self._mood))
            if len(self._mood_history) > 200:
                self._mood_history = self._mood_history[-200:]
            if self._dir is not None:
                self._save_mood()
            self.emit_event("personality.mood_changed", dict(self._mood))
            return True

    def get_mood(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._mood)

    def get_mood_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._mood_history)

    def influence_response_style(self) -> Dict[str, Any]:
        with self._lock:
            traits = {t: float(r.value) for t, r in self._traits.items()}
            openness = traits.get(PersonalityTrait.OPENNESS, _DEFAULT_TRAIT_VALUE)
            conscientiousness = traits.get(PersonalityTrait.CONSCIENTIOUSNESS, _DEFAULT_TRAIT_VALUE)
            extraversion = traits.get(PersonalityTrait.EXTRAVERSION, _DEFAULT_TRAIT_VALUE)
            agreeableness = traits.get(PersonalityTrait.AGREEABLENESS, _DEFAULT_TRAIT_VALUE)
            neuroticism = traits.get(PersonalityTrait.NEUROTICISM, _DEFAULT_TRAIT_VALUE)

            verbosity = max(0.0, min(1.0, 0.4 + extraversion * 0.5 - conscientiousness * 0.1))
            creativity = max(0.0, min(1.0, openness * 0.9 + 0.05))
            warmth = max(0.0, min(1.0, agreeableness * 0.8 + 0.1))
            risk_taking = max(0.0, min(1.0, openness * 0.5 + extraversion * 0.3 - neuroticism * 0.4 + 0.2))
            structure = max(0.0, min(1.0, conscientiousness * 0.9 + 0.05))
            tone = self._map_tone(extraversion, agreeableness, neuroticism)
            mood = dict(self._mood)
            mood_factor = float(mood.get("valence", 0.5))
            verbosity = max(0.0, min(1.0, verbosity * (0.8 + mood_factor * 0.4)))
            return {
                "tone": tone,
                "verbosity": round(verbosity, 3),
                "creativity": round(creativity, 3),
                "warmth": round(warmth, 3),
                "risk_taking": round(risk_taking, 3),
                "structure": round(structure, 3),
                "mood_label": mood.get("label", "neutral"),
                "mood_valence": round(mood_factor, 3),
                "mood_arousal": round(float(mood.get("arousal", 0.5)), 3),
                "underlying_traits": {
                    "openness": round(openness, 3),
                    "conscientiousness": round(conscientiousness, 3),
                    "extraversion": round(extraversion, 3),
                    "agreeableness": round(agreeableness, 3),
                    "neuroticism": round(neuroticism, 3),
                },
            }

    @staticmethod
    def _map_tone(extraversion: float, agreeableness: float, neuroticism: float) -> str:
        if extraversion >= 0.7 and agreeableness >= 0.6:
            return "warm_enthusiastic"
        if extraversion >= 0.6 and agreeableness < 0.5:
            return "direct_confident"
        if extraversion < 0.4 and agreeableness >= 0.6:
            return "gentle_considerate"
        if extraversion < 0.4 and agreeableness < 0.5:
            return "reserved_neutral"
        if neuroticism >= 0.7:
            return "cautious_thoughtful"
        return "balanced"

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        try:
            payload = {
                "module_id": self.MODULE_ID,
                "module_version": self.MODULE_VERSION,
                "drift_learning_rate": self._drift_learning_rate,
                "updated_at": _now_iso(),
            }
            self._state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save personality state: %s", exc)

    def _save_traits(self) -> None:
        if self._traits_path is None:
            return
        try:
            payload = {t.value: r.to_dict() for t, r in self._traits.items()}
            self._traits_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save traits: %s", exc)

    def _save_experiences(self) -> None:
        if self._experiences_path is None:
            return
        try:
            payload = {eid: e.to_dict() for eid, e in self._experiences.items()}
            self._experiences_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save experiences: %s", exc)

    def _save_snapshots(self) -> None:
        if self._snapshots_path is None:
            return
        try:
            payload = {sid: s.to_dict() for sid, s in self._snapshots.items()}
            self._snapshots_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save snapshots: %s", exc)

    def _save_mood(self) -> None:
        if self._mood_path is None:
            return
        try:
            payload = {
                "current": dict(self._mood),
                "history": list(self._mood_history),
            }
            self._mood_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save mood: %s", exc)

    def _load_from_state(self) -> None:
        if self._dir is None:
            return
        try:
            if self._state_path and self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._drift_learning_rate = max(
                        0.0,
                        min(1.0, float(data.get("drift_learning_rate", self._drift_learning_rate))),
                    )
            if self._traits_path and self._traits_path.exists():
                data = json.loads(self._traits_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    loaded: Dict[PersonalityTrait, TraitRecord] = {}
                    for k, v in data.items():
                        if isinstance(v, dict):
                            try:
                                loaded[PersonalityTrait(k)] = TraitRecord.from_dict(v)
                            except (KeyError, ValueError):
                                continue
                    if loaded:
                        self._traits = loaded
            if self._experiences_path and self._experiences_path.exists():
                data = json.loads(self._experiences_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    loaded_exp: Dict[str, Experience] = {}
                    for k, v in data.items():
                        if isinstance(v, dict):
                            try:
                                loaded_exp[k] = Experience.from_dict(v)
                            except (KeyError, ValueError, TypeError):
                                continue
                    self._experiences = loaded_exp
            if self._snapshots_path and self._snapshots_path.exists():
                data = json.loads(self._snapshots_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    loaded_snap: Dict[str, PersonalitySnapshot] = {}
                    for k, v in data.items():
                        if isinstance(v, dict):
                            try:
                                loaded_snap[k] = PersonalitySnapshot.from_dict(v)
                            except (KeyError, ValueError, TypeError):
                                continue
                    self._snapshots = loaded_snap
            if self._mood_path and self._mood_path.exists():
                data = json.loads(self._mood_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    current = data.get("current")
                    if isinstance(current, dict):
                        self._mood = {
                            "valence": float(current.get("valence", _DEFAULT_TRAIT_VALUE)),
                            "arousal": float(current.get("arousal", _DEFAULT_TRAIT_VALUE)),
                            "label": str(current.get("label", "neutral")),
                            "updated_at": str(current.get("updated_at", _now_iso())),
                        }
                    history = data.get("history")
                    if isinstance(history, list):
                        self._mood_history = [dict(x) for x in history if isinstance(x, dict)]
        except Exception as exc:
            logger.warning("Failed to load personality state: %s", exc)


_singleton: Optional[PersonalityDevelopmentSystem] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/personality_system"


def get_personality_system(storage_dir: Optional[str] = None) -> PersonalityDevelopmentSystem:
    global _singleton, _DEFAULT_DIR
    with _singleton_lock:
        if _singleton is None:
            target_dir = storage_dir or _DEFAULT_DIR
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            _singleton = PersonalityDevelopmentSystem(storage_dir=target_dir)
            if storage_dir is not None:
                _DEFAULT_DIR = storage_dir
    return _singleton


__all__ = [
    "Experience",
    "PersonalityDevelopmentSystem",
    "PersonalitySnapshot",
    "PersonalityTrait",
    "TraitRecord",
    "get_personality_system",
]
