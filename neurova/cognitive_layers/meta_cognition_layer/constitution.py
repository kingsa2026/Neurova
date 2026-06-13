from __future__ import annotations

import datetime
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.base_module import BaseModule, ModuleState

logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ViolationLevel(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class ValuePrinciple(str, Enum):
    SAFETY = "safety"
    HONESTY = "honesty"
    PRIVACY = "privacy"
    FAIRNESS = "fairness"
    AUTONOMY = "autonomy"
    BENEFICENCE = "beneficence"
    NON_MALEFICENCE = "non_maleficence"
    JUSTICE = "justice"


_VIOLATION_RANK: Dict[str, int] = {
    ViolationLevel.NONE.value: 0,
    ViolationLevel.MINOR.value: 1,
    ViolationLevel.MODERATE.value: 2,
    ViolationLevel.SEVERE.value: 3,
    ViolationLevel.CRITICAL.value: 4,
}


_DEFAULT_BOUNDARIES: List[Dict[str, Any]] = [
    {
        "name": "no_physical_harm",
        "description": "no physical harm",
        "violation_level": ViolationLevel.CRITICAL,
        "conditions": ["kill", "harm", "injure", "attack", "weapon", "bomb"],
        "exceptions": [],
    },
    {
        "name": "no_illegal_activity",
        "description": "no illegal assistance",
        "violation_level": ViolationLevel.SEVERE,
        "conditions": ["steal", "fraud", "hack", "illegal", "phish"],
        "exceptions": ["legal", "lawful"],
    },
    {
        "name": "privacy_protection",
        "description": "protect privacy",
        "violation_level": ViolationLevel.SEVERE,
        "conditions": ["ssn", "credit_card", "pii", "personal_data"],
        "exceptions": ["redacted", "masked"],
    },
    {
        "name": "no_deception",
        "description": "no deception",
        "violation_level": ViolationLevel.MODERATE,
        "conditions": ["lie", "deceive", "mislead"],
        "exceptions": ["fiction", "story", "imagine"],
    },
    {
        "name": "respect_autonomy",
        "description": "respect autonomy",
        "violation_level": ViolationLevel.MINOR,
        "conditions": ["force", "coerce", "manipulate"],
        "exceptions": ["emergency"],
    },
]


_DEFAULT_VALUES: List[Dict[str, Any]] = [
    {
        "principle": ValuePrinciple.SAFETY,
        "name": "safety_first",
        "description": "safety first",
        "weight": 1.0,
        "conditions": ["safe", "danger", "risk"],
    },
    {
        "principle": ValuePrinciple.HONESTY,
        "name": "be_truthful",
        "description": "be truthful",
        "weight": 0.95,
        "conditions": ["truth", "honest", "lie"],
    },
    {
        "principle": ValuePrinciple.PRIVACY,
        "name": "protect_privacy",
        "description": "protect privacy",
        "weight": 0.9,
        "conditions": ["private", "personal", "privacy"],
    },
    {
        "principle": ValuePrinciple.FAIRNESS,
        "name": "be_fair",
        "description": "be fair",
        "weight": 0.85,
        "conditions": ["fair", "bias", "discriminate"],
    },
    {
        "principle": ValuePrinciple.AUTONOMY,
        "name": "respect_autonomy",
        "description": "respect autonomy",
        "weight": 0.8,
        "conditions": ["choice", "decide"],
    },
    {
        "principle": ValuePrinciple.BENEFICENCE,
        "name": "do_good",
        "description": "do good",
        "weight": 0.9,
        "conditions": ["help", "benefit", "good"],
    },
    {
        "principle": ValuePrinciple.NON_MALEFICENCE,
        "name": "do_no_harm",
        "description": "do no harm",
        "weight": 1.0,
        "conditions": ["harm", "damage"],
    },
    {
        "principle": ValuePrinciple.JUSTICE,
        "name": "be_just",
        "description": "be just",
        "weight": 0.85,
        "conditions": ["justice", "rights"],
    },
]


@dataclass
class CoreBoundary:
    boundary_id: str
    name: str
    description: str
    violation_level: ViolationLevel
    conditions: List[str] = None
    exceptions: List[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.conditions is None:
            self.conditions = []
        if self.exceptions is None:
            self.exceptions = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "name": self.name,
            "description": self.description,
            "violation_level": self.violation_level.value,
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreBoundary":
        return cls(
            boundary_id=data["boundary_id"],
            name=data["name"],
            description=data["description"],
            violation_level=ViolationLevel(data["violation_level"]),
            conditions=list(data.get("conditions", [])),
            exceptions=list(data.get("exceptions", [])),
            enabled=bool(data.get("enabled", True)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ValueRule:
    rule_id: str
    principle: ValuePrinciple
    name: str
    description: str
    weight: float = 1.0
    conditions: List[str] = None
    exceptions: List[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.conditions is None:
            self.conditions = []
        if self.exceptions is None:
            self.exceptions = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "principle": self.principle.value,
            "name": self.name,
            "description": self.description,
            "weight": float(self.weight),
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValueRule":
        return cls(
            rule_id=data["rule_id"],
            principle=ValuePrinciple(data["principle"]),
            name=data["name"],
            description=data["description"],
            weight=float(data.get("weight", 1.0)),
            conditions=list(data.get("conditions", [])),
            exceptions=list(data.get("exceptions", [])),
            enabled=bool(data.get("enabled", True)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ActionEvaluation:
    action_id: str
    action_description: str
    violation_level: ViolationLevel
    boundary_violations: List[str] = None
    value_compliance: Dict[str, float] = None
    overall_score: float = 0.0
    reasoning: str = ""
    recommendations: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.boundary_violations is None:
            self.boundary_violations = []
        if self.value_compliance is None:
            self.value_compliance = {}
        if self.recommendations is None:
            self.recommendations = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_description": self.action_description,
            "violation_level": self.violation_level.value,
            "boundary_violations": list(self.boundary_violations),
            "value_compliance": dict(self.value_compliance),
            "overall_score": float(self.overall_score),
            "reasoning": self.reasoning,
            "recommendations": list(self.recommendations),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionEvaluation":
        return cls(
            action_id=data["action_id"],
            action_description=data["action_description"],
            violation_level=ViolationLevel(data["violation_level"]),
            boundary_violations=list(data.get("boundary_violations", [])),
            value_compliance=dict(data.get("value_compliance", {})),
            overall_score=float(data.get("overall_score", 0.0)),
            reasoning=data.get("reasoning", ""),
            recommendations=list(data.get("recommendations", [])),
            metadata=dict(data.get("metadata", {})),
        )


class AgentConstitution(BaseModule):
    MODULE_ID = "agent_constitution"
    MODULE_NAME = "Agent Constitution"
    MODULE_VERSION = "1.0.0"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Any = None,
        storage_dir: Optional[str] = None,
        refusal_template: Optional[str] = None,
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
        self._refusal_template = refusal_template or (
            "I cannot perform this action because it would violate the {boundary_name} "
            "boundary ({violation_level} violation): {description}."
        )
        self._boundaries: Dict[str, CoreBoundary] = {}
        self._values: Dict[str, ValueRule] = {}
        self._history: Dict[str, ActionEvaluation] = {}
        self._lock = threading.RLock()

        if storage_dir:
            self._dir = Path(storage_dir)
            self._dir.mkdir(parents=True, exist_ok=True)
            self._boundaries_path = self._dir / "boundaries.json"
            self._values_path = self._dir / "values.json"
            self._history_path = self._dir / "history.json"
        else:
            self._dir = None
            self._boundaries_path = None
            self._values_path = None
            self._history_path = None

        self._init_core_boundaries()
        self._init_value_system()
        if self._dir is not None:
            self._load()
            self._save_boundaries()
            self._save_values()

    def on_initialize(self) -> None:
        self.set_state(ModuleState.INITIALIZING)
        self._init_core_boundaries()
        self._init_value_system()
        if self._dir is not None:
            self._load()
        self.set_state(ModuleState.INITIALIZED)

    def on_start(self) -> None:
        self.set_state(ModuleState.RUNNING)

    def on_stop(self) -> None:
        self.set_state(ModuleState.STOPPED)

    def _init_core_boundaries(self) -> None:
        with self._lock:
            if self._boundaries:
                return
            for spec in _DEFAULT_BOUNDARIES:
                bid = _new_id("bd_")
                boundary = CoreBoundary(
                    boundary_id=bid,
                    name=spec["name"],
                    description=spec["description"],
                    violation_level=spec["violation_level"],
                    conditions=list(spec.get("conditions", [])),
                    exceptions=list(spec.get("exceptions", [])),
                )
                self._boundaries[bid] = boundary

    def _init_value_system(self) -> None:
        with self._lock:
            if self._values:
                return
            for spec in _DEFAULT_VALUES:
                rid = _new_id("vr_")
                rule = ValueRule(
                    rule_id=rid,
                    principle=spec["principle"],
                    name=spec["name"],
                    description=spec["description"],
                    weight=float(spec.get("weight", 1.0)),
                    conditions=list(spec.get("conditions", [])),
                )
                self._values[rid] = rule

    def evaluate_action(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ActionEvaluation:
        with self._lock:
            action_id = _new_id("act_")
            boundary_violations = self._check_boundary_violation(action)
            value_compliance = self._evaluate_value_compliance(action, context or {})
            violation_level = self._calculate_boundary_score(boundary_violations)
            overall = self._compute_overall_score(violation_level, value_compliance)
            reasoning = self._generate_reasoning(action, boundary_violations, value_compliance, violation_level)
            recommendations = self._generate_suggestions(action, boundary_violations, violation_level)
            evaluation = ActionEvaluation(
                action_id=action_id,
                action_description=action,
                violation_level=violation_level,
                boundary_violations=boundary_violations,
                value_compliance=value_compliance,
                overall_score=overall,
                reasoning=reasoning,
                recommendations=recommendations,
                metadata=dict(context) if context else {},
            )
            self._add_to_history(evaluation)
            self.emit_event("constitution.action_evaluated", evaluation.to_dict())
            return evaluation

    def _check_boundary_violation(self, action: str) -> List[str]:
        action_lower = (action or "").lower()
        violations: List[str] = []
        with self._lock:
            boundaries = list(self._boundaries.values())
        for boundary in boundaries:
            if not boundary.enabled:
                continue
            if self._boundary_matches(boundary, action_lower):
                violations.append(boundary.name)
        return violations

    def _boundary_matches(self, boundary: CoreBoundary, action_lower: str) -> bool:
        if not action_lower:
            return False
        has_condition = False
        for cond in boundary.conditions:
            token = (cond or "").lower().strip()
            if token and token in action_lower:
                has_condition = True
                break
        if not has_condition:
            return False
        for exc in boundary.exceptions:
            token = (exc or "").lower().strip()
            if token and token in action_lower:
                return False
        return True

    def _evaluate_value_compliance(self, action: str, context: Dict[str, Any]) -> Dict[str, float]:
        action_lower = (action or "").lower()
        result: Dict[str, float] = {}
        with self._lock:
            values = list(self._values.values())
        for rule in values:
            if not rule.enabled:
                result[rule.principle.value] = 0.5
                continue
            base = 0.7
            for cond in rule.conditions:
                token = (cond or "").lower().strip()
                if token and token in action_lower:
                    if rule.principle in (
                        ValuePrinciple.SAFETY,
                        ValuePrinciple.HONESTY,
                        ValuePrinciple.PRIVACY,
                        ValuePrinciple.NON_MALEFICENCE,
                    ):
                        base -= 0.05
                    else:
                        base += 0.05
            weight = max(0.0, min(1.0, float(rule.weight)))
            result[rule.principle.value] = round(max(0.0, min(1.0, base)) * weight, 3)
        return result

    def _calculate_boundary_score(self, violations: List[str]) -> ViolationLevel:
        if not violations:
            return ViolationLevel.NONE
        max_level = ViolationLevel.NONE
        max_rank = 0
        with self._lock:
            for name in violations:
                boundary = next((b for b in self._boundaries.values() if b.name == name), None)
                if boundary is None:
                    continue
                rank = _VIOLATION_RANK.get(boundary.violation_level.value, 0)
                if rank > max_rank:
                    max_rank = rank
                    max_level = boundary.violation_level
        return max_level

    def _compute_overall_score(self, violation_level: ViolationLevel, value_compliance: Dict[str, float]) -> float:
        violation_penalty = _VIOLATION_RANK.get(violation_level.value, 0) * 0.2
        if value_compliance:
            avg_value = sum(value_compliance.values()) / len(value_compliance)
        else:
            avg_value = 0.5
        score = max(0.0, min(1.0, avg_value - violation_penalty))
        return round(score, 3)

    def _generate_reasoning(
        self,
        action: str,
        violations: List[str],
        value_compliance: Dict[str, float],
        violation_level: ViolationLevel,
    ) -> str:
        if not violations:
            return (
                f"Action '{action[:80]}' complies with all active boundaries. "
                f"Value alignment: {len(value_compliance)} principles evaluated."
            )
        joined = ", ".join(violations)
        return (
            f"Action '{action[:80]}' violates {len(violations)} boundary/boundaries "
            f"({joined}); highest severity: {violation_level.value}."
        )

    def _generate_suggestions(
        self,
        action: str,
        violations: List[str],
        violation_level: ViolationLevel,
    ) -> List[str]:
        if not violations:
            return []
        suggestions = [
            f"Reframe the action to avoid triggering: {', '.join(violations)}",
        ]
        if violation_level == ViolationLevel.CRITICAL:
            suggestions.append("Do not execute this action under any circumstance.")
        elif violation_level == ViolationLevel.SEVERE:
            suggestions.append("Request human review before proceeding.")
        else:
            suggestions.append("Consider safer alternatives or additional context.")
        return suggestions

    def _add_to_history(self, evaluation: ActionEvaluation) -> None:
        with self._lock:
            eval_copy = ActionEvaluation(
                action_id=evaluation.action_id,
                action_description=evaluation.action_description,
                violation_level=evaluation.violation_level,
                boundary_violations=list(evaluation.boundary_violations),
                value_compliance=dict(evaluation.value_compliance),
                overall_score=evaluation.overall_score,
                reasoning=evaluation.reasoning,
                recommendations=list(evaluation.recommendations),
                metadata=dict(evaluation.metadata),
            )
            meta = dict(eval_copy.metadata)
            meta["evaluated_at"] = _now_iso()
            eval_copy.metadata = meta
            self._history[eval_copy.action_id] = eval_copy
            if len(self._history) > 500:
                sorted_items = sorted(
                    self._history.items(),
                    key=lambda kv: kv[1].metadata.get("evaluated_at", ""),
                )
                keep = sorted_items[-500:]
                self._history = {k: v for k, v in keep}
            self._save_history()

    def can_refuse_request(self, request: str) -> bool:
        with self._lock:
            evaluation = self.evaluate_action(request)
            return evaluation.violation_level in (
                ViolationLevel.SEVERE,
                ViolationLevel.CRITICAL,
            )

    def get_refusal_message(self, request: str) -> Optional[str]:
        with self._lock:
            evaluation = self.evaluate_action(request)
            if evaluation.violation_level not in (
                ViolationLevel.SEVERE,
                ViolationLevel.CRITICAL,
            ):
                return None
            if evaluation.boundary_violations:
                boundary_name = evaluation.boundary_violations[0]
            else:
                boundary_name = "core"
            return self._refusal_template.format(
                boundary_name=boundary_name,
                violation_level=evaluation.violation_level.value,
                description="see constitution rules",
                request=request[:120],
            )

    def get_boundary_by_id(self, boundary_id: str) -> Optional[CoreBoundary]:
        with self._lock:
            b = self._boundaries.get(boundary_id)
            return b

    def get_all_boundaries(self) -> List[CoreBoundary]:
        with self._lock:
            return list(self._boundaries.values())

    def get_all_values(self) -> List[ValueRule]:
        with self._lock:
            return list(self._values.values())

    def get_evaluation_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = [e.to_dict() for e in self._history.values()]
            items.sort(key=lambda d: d.get("metadata", {}).get("evaluated_at", ""))
            if limit is not None:
                items = items[-int(limit) :]
            return items

    def get_constitution_summary(self) -> Dict[str, Any]:
        with self._lock:
            boundaries = list(self._boundaries.values())
            values = list(self._values.values())
            by_level: Dict[str, int] = {}
            for b in boundaries:
                lv = b.violation_level.value
                by_level[lv] = by_level.get(lv, 0) + 1
            by_principle: Dict[str, int] = {}
            total_weight = 0.0
            for v in values:
                p = v.principle.value
                by_principle[p] = by_principle.get(p, 0) + 1
                total_weight += float(v.weight)
            avg_weight = (total_weight / len(values)) if values else 0.0
            return {
                "boundary_count": len(boundaries),
                "value_count": len(values),
                "history_count": len(self._history),
                "boundaries_by_level": by_level,
                "values_by_principle": by_principle,
                "avg_value_weight": round(avg_weight, 3),
            }

    def _handle_evaluate_request(self, *args: Any, **kwargs: Any) -> None:
        return None

    def _handle_boundary_check(self, *args: Any, **kwargs: Any) -> None:
        return None

    def validate_action(self, action: str) -> bool:
        with self._lock:
            evaluation = self.evaluate_action(action)
            return evaluation.violation_level not in (
                ViolationLevel.SEVERE,
                ViolationLevel.CRITICAL,
            )

    def add_boundary(
        self,
        name: str,
        description: str,
        violation_level: ViolationLevel,
        conditions: Optional[List[str]] = None,
        exceptions: Optional[List[str]] = None,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            bid = _new_id("bd_")
            boundary = CoreBoundary(
                boundary_id=bid,
                name=name,
                description=description,
                violation_level=violation_level,
                conditions=list(conditions) if conditions else [],
                exceptions=list(exceptions) if exceptions else [],
                enabled=enabled,
                metadata=dict(metadata) if metadata else {},
            )
            self._boundaries[bid] = boundary
            self._save_boundaries()
            return bid

    def amend_boundary(
        self,
        boundary_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        violation_level: Optional[ViolationLevel] = None,
        conditions: Optional[List[str]] = None,
        exceptions: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            boundary = self._boundaries.get(boundary_id)
            if boundary is None:
                return False
            if name is not None:
                boundary.name = name
            if description is not None:
                boundary.description = description
            if violation_level is not None:
                boundary.violation_level = violation_level
            if conditions is not None:
                boundary.conditions = list(conditions)
            if exceptions is not None:
                boundary.exceptions = list(exceptions)
            if enabled is not None:
                boundary.enabled = enabled
            if metadata is not None:
                boundary.metadata = dict(metadata)
            self._save_boundaries()
            return True

    def add_value_rule(
        self,
        principle: ValuePrinciple,
        name: str,
        description: str,
        weight: float = 1.0,
        conditions: Optional[List[str]] = None,
        exceptions: Optional[List[str]] = None,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            rid = _new_id("vr_")
            rule = ValueRule(
                rule_id=rid,
                principle=principle,
                name=name,
                description=description,
                weight=max(0.0, min(1.0, float(weight))),
                conditions=list(conditions) if conditions else [],
                exceptions=list(exceptions) if exceptions else [],
                enabled=enabled,
                metadata=dict(metadata) if metadata else {},
            )
            self._values[rid] = rule
            self._save_values()
            return rid

    def _load(self) -> None:
        if self._dir is None:
            return
        try:
            if self._boundaries_path and self._boundaries_path.exists():
                data = json.loads(self._boundaries_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            self._boundaries[k] = CoreBoundary.from_dict(v)
            if self._values_path and self._values_path.exists():
                data = json.loads(self._values_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            self._values[k] = ValueRule.from_dict(v)
            if self._history_path and self._history_path.exists():
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            self._history[k] = ActionEvaluation.from_dict(v)
        except Exception as exc:
            logger.warning("Failed to load constitution state: %s", exc)

    def _save_boundaries(self) -> None:
        if self._boundaries_path is None:
            return
        try:
            self._boundaries_path.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in self._boundaries.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save boundaries: %s", exc)

    def _save_values(self) -> None:
        if self._values_path is None:
            return
        try:
            self._values_path.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in self._values.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save values: %s", exc)

    def _save_history(self) -> None:
        if self._history_path is None:
            return
        try:
            self._history_path.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in self._history.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save history: %s", exc)


_singleton: Optional[AgentConstitution] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/constitution"


def get_constitution(storage_dir: Optional[str] = None) -> AgentConstitution:
    global _singleton, _DEFAULT_DIR
    with _singleton_lock:
        if _singleton is None:
            target_dir = storage_dir or _DEFAULT_DIR
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            _singleton = AgentConstitution(storage_dir=target_dir)
            if storage_dir is not None:
                _DEFAULT_DIR = storage_dir
    return _singleton


__all__ = [
    "ActionEvaluation",
    "AgentConstitution",
    "CoreBoundary",
    "ValuePrinciple",
    "ValueRule",
    "ViolationLevel",
    "get_constitution",
]
