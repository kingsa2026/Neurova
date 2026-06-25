from __future__ import annotations

"""
Agent 自主决策系统 - 实现 Agent 自主做出选择的能力
"""

import datetime
import json
from neurova.core.logger import get_logger
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.base_module import BaseModule, ModuleState

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DecisionType(str, Enum):
    ROUTINE = "routine"
    STRATEGIC = "strategic"
    TACTICAL = "tactical"
    EMERGENCY = "emergency"
    CREATIVE = "creative"
    ETHICAL = "ethical"


class ChoiceStatus(str, Enum):
    PENDING = "pending"
    EVALUATED = "evaluated"
    SELECTED = "selected"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass
class Choice:
    choice_id: str
    description: str
    actions: List[str]
    pros: List[str] = None
    cons: List[str] = None
    score: float = 0.0
    risk_level: float = 0.0
    feasibility: float = 0.0
    status: ChoiceStatus = ChoiceStatus.PENDING
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.pros is None:
            self.pros = []
        if self.cons is None:
            self.cons = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "choice_id": self.choice_id,
            "description": self.description,
            "actions": list(self.actions),
            "pros": list(self.pros),
            "cons": list(self.cons),
            "score": float(self.score),
            "risk_level": float(self.risk_level),
            "feasibility": float(self.feasibility),
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Choice":
        return cls(
            choice_id=data["choice_id"],
            description=data["description"],
            actions=list(data.get("actions", [])),
            pros=list(data.get("pros", [])),
            cons=list(data.get("cons", [])),
            score=float(data.get("score", 0.0)),
            risk_level=float(data.get("risk_level", 0.0)),
            feasibility=float(data.get("feasibility", 0.0)),
            status=ChoiceStatus(data.get("status", "pending")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class DecisionContext:
    context_id: str
    situation: str
    goals: List[str]
    constraints: List[str] = None
    available_resources: List[str] = None
    time_pressure: float = 0.0
    uncertainty: float = 0.0
    stakes: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.constraints is None:
            self.constraints = []
        if self.available_resources is None:
            self.available_resources = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "situation": self.situation,
            "goals": list(self.goals),
            "constraints": list(self.constraints),
            "available_resources": list(self.available_resources),
            "time_pressure": float(self.time_pressure),
            "uncertainty": float(self.uncertainty),
            "stakes": float(self.stakes),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionContext":
        return cls(
            context_id=data["context_id"],
            situation=data["situation"],
            goals=list(data.get("goals", [])),
            constraints=list(data.get("constraints", [])),
            available_resources=list(data.get("available_resources", [])),
            time_pressure=float(data.get("time_pressure", 0.0)),
            uncertainty=float(data.get("uncertainty", 0.0)),
            stakes=float(data.get("stakes", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class Decision:
    decision_id: str
    decision_type: DecisionType
    context: DecisionContext
    choices: List[Choice]
    selected_choice: Optional[Choice] = None
    reasoning: str = ""
    confidence: float = 0.0
    execution_time: float = 0.0
    outcome: str = ""
    lessons_learned: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.lessons_learned is None:
            self.lessons_learned = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "context": self.context.to_dict(),
            "choices": [c.to_dict() for c in self.choices],
            "selected_choice": self.selected_choice.to_dict() if self.selected_choice else None,
            "reasoning": self.reasoning,
            "confidence": float(self.confidence),
            "execution_time": float(self.execution_time),
            "outcome": self.outcome,
            "lessons_learned": list(self.lessons_learned),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Decision":
        return cls(
            decision_id=data["decision_id"],
            decision_type=DecisionType(data["decision_type"]),
            context=DecisionContext.from_dict(data["context"]),
            choices=[Choice.from_dict(c) for c in data.get("choices", [])],
            selected_choice=Choice.from_dict(data["selected_choice"]) if data.get("selected_choice") else None,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.0)),
            execution_time=float(data.get("execution_time", 0.0)),
            outcome=data.get("outcome", ""),
            lessons_learned=list(data.get("lessons_learned", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AgentPreference:
    preference_id: str
    category: str
    value: Any
    weight: float = 1.0
    description: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.created_at == 0.0 or self.created_at is None:
            self.created_at = time.time()
        if self.updated_at == 0.0 or self.updated_at is None:
            self.updated_at = self.created_at
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preference_id": self.preference_id,
            "category": self.category,
            "value": self.value,
            "weight": float(self.weight),
            "description": self.description,
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentPreference":
        return cls(
            preference_id=data["preference_id"],
            category=data["category"],
            value=data["value"],
            weight=float(data.get("weight", 1.0)),
            description=data.get("description", ""),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


_DEFAULT_PREFERENCES: List[Dict[str, Any]] = [
    {"category": "style", "value": "balanced", "weight": 0.5, "description": "default communication style"},
    {"category": "verbosity", "value": "moderate", "weight": 0.5, "description": "default response verbosity"},
    {"category": "creativity", "value": "balanced", "weight": 0.5, "description": "default creative output level"},
    {"category": "tone", "value": "neutral", "weight": 0.5, "description": "default interaction tone"},
    {"category": "risk_tolerance", "value": "moderate", "weight": 0.5, "description": "default risk tolerance"},
    {"category": "formality", "value": "balanced", "weight": 0.5, "description": "default formality level"},
]


_RISKY_ACTION_KEYWORDS: List[str] = [
    "delete",
    "drop",
    "remove",
    "destroy",
    "shutdown",
    "kill",
    "production",
    "database",
    "truncate",
    "rm -rf",
    "format",
    "drop_table",
    "drop_db",
    "sudo",
    "admin",
    "wipe",
    "reset_all",
    "terminate",
    "halt_system",
    "exec_code",
]

_URGENT_KEYWORDS: List[str] = [
    "emergency",
    "urgent",
    "asap",
    "immediate",
    "critical",
    "fire",
    "outage",
    "down",
]

_MEDIUM_URGENCY_KEYWORDS: List[str] = [
    "soon",
    "today",
    "quick",
    "fast",
    "deadline",
    "rush",
]

_COMPLEX_KEYWORDS: List[str] = [
    "integrate",
    "architect",
    "design",
    "migrate",
    "refactor",
    "deploy",
    "multi",
    "distributed",
    "concurrent",
    "pipeline",
    "scale",
]


class AgentAutonomySystem(BaseModule):
    MODULE_ID = "agent_autonomy_system"
    MODULE_NAME = "Agent Autonomy System"
    MODULE_VERSION = "1.0.0"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Any = None,
        storage_dir: Optional[str] = None,
        autonomy_level: float = 0.5,
        constraints: Optional[List[str]] = None,
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
        self._autonomy_level: float = max(0.0, min(1.0, float(autonomy_level)))
        self._constraints: List[str] = [str(c) for c in (constraints or [])]
        self._preferences: Dict[str, AgentPreference] = {}
        self._decision_history: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

        if storage_dir:
            self._dir = Path(storage_dir)
            self._dir.mkdir(parents=True, exist_ok=True)
            self._state_path = self._dir / "autonomy_state.json"
            self._prefs_path = self._dir / "preferences.json"
            self._history_path = self._dir / "decision_history.json"
            self._constraints_path = self._dir / "constraints.json"
        else:
            self._dir = None
            self._state_path = None
            self._prefs_path = None
            self._history_path = None
            self._constraints_path = None

        self._init_preferences()
        if self._dir is not None:
            self._load()
            self._save_all()

    def on_initialize(self) -> None:
        self.set_state(ModuleState.INITIALIZING)
        if not self._preferences:
            self._init_preferences()
        if self._dir is not None:
            self._load()
        self.set_state(ModuleState.INITIALIZED)

    def on_start(self) -> None:
        self.set_state(ModuleState.RUNNING)

    def on_stop(self) -> None:
        self.set_state(ModuleState.STOPPED)

    def _init_preferences(self) -> None:
        with self._lock:
            for spec in _DEFAULT_PREFERENCES:
                cat = spec["category"]
                if cat in self._preferences:
                    continue
                self._preferences[cat] = AgentPreference(
                    preference_id=_new_id("pref_"),
                    category=cat,
                    value=spec["value"],
                    weight=float(spec["weight"]),
                    description=spec.get("description", ""),
                )

    def autonomy_level(self) -> float:
        with self._lock:
            return float(self._autonomy_level)

    def set_autonomy_level(self, value: float) -> bool:
        with self._lock:
            self._autonomy_level = max(0.0, min(1.0, float(value)))
            if self._dir is not None:
                self._save_state()
            return True

    def get_constraints(self) -> List[str]:
        with self._lock:
            return list(self._constraints)

    def add_constraint(self, constraint: str) -> bool:
        with self._lock:
            c = str(constraint)
            if c and c not in self._constraints:
                self._constraints.append(c)
                if self._dir is not None:
                    self._save_constraints()
            return True

    def remove_constraint(self, constraint: str) -> bool:
        with self._lock:
            c = str(constraint)
            if c in self._constraints:
                self._constraints.remove(c)
                if self._dir is not None:
                    self._save_constraints()
                return True
            return False

    def evaluate_situation(
        self,
        situation: str,
        goals: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = (situation or "").lower()
        goals_list = list(goals or [])
        urgency = self._assess_urgency(text)
        complexity = self._assess_complexity(text, goals_list)
        recommended = self._recommend_approach(urgency, complexity, text)
        return {
            "urgency": round(float(urgency), 4),
            "complexity": round(float(complexity), 4),
            "recommended_approach": recommended,
            "situation": situation,
            "goals": goals_list,
            "context": dict(context) if context else {},
        }

    def _assess_urgency(self, text: str) -> float:
        score = 0.15
        for kw in _URGENT_KEYWORDS:
            if kw in text:
                score += 0.30
        for kw in _MEDIUM_URGENCY_KEYWORDS:
            if kw in text:
                score += 0.12
        return max(0.0, min(1.0, score))

    def _assess_complexity(self, text: str, goals: List[str]) -> float:
        score = 0.15
        if len(goals) > 1:
            score += min(0.3, 0.08 * len(goals))
        if len(text) > 200:
            score += 0.18
        long_words = sum(1 for w in text.split() if len(w) > 10)
        score += min(0.18, 0.04 * long_words)
        for kw in _COMPLEX_KEYWORDS:
            if kw in text:
                score += 0.08
        return max(0.0, min(1.0, score))

    def _recommend_approach(self, urgency: float, complexity: float, text: str) -> str:
        if urgency >= 0.7:
            return "act_immediately"
        if complexity >= 0.7:
            return "decompose_and_plan"
        if any(kw in text for kw in ("creative", "story", "poem", "imagine")):
            return "creative_exploration"
        if complexity >= 0.4:
            return "structured_approach"
        if "ethical" in text or "moral" in text:
            return "consult_principles"
        return "direct_response"

    def generate_choices(
        self,
        situation: str,
        num_choices: int = 2,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Choice]:
        n = max(1, int(num_choices))
        bases = self._get_base_choices(situation)
        out: List[Choice] = []
        for i in range(n):
            base = bases[i % len(bases)]
            description = self._generate_choice_description(base["template"], situation, i)
            actions = [a.replace("{situation}", situation) for a in base["actions"]]
            ch = Choice(
                choice_id=_new_id("ch_"),
                description=description,
                actions=actions,
                pros=list(base.get("pros", [])),
                cons=list(base.get("cons", [])),
                risk_level=float(base.get("risk_level", 0.2)),
                feasibility=float(base.get("feasibility", 0.7)),
                status=ChoiceStatus.PENDING,
            )
            out.append(ch)
        return out

    def _get_base_choices(self, situation: str) -> List[Dict[str, Any]]:
        return [
            {
                "template": "conservative",
                "description": "Conservative approach",
                "actions": ["analyze {situation}", "validate before acting"],
                "pros": ["low risk", "predictable outcome"],
                "cons": ["may be slow"],
                "risk_level": 0.1,
                "feasibility": 0.9,
            },
            {
                "template": "balanced",
                "description": "Balanced approach",
                "actions": ["plan briefly", "execute {situation}"],
                "pros": ["balanced tradeoffs"],
                "cons": ["requires more thought"],
                "risk_level": 0.4,
                "feasibility": 0.7,
            },
            {
                "template": "bold",
                "description": "Bold approach",
                "actions": ["act decisively on {situation}", "iterate quickly"],
                "pros": ["fast results"],
                "cons": ["higher error rate"],
                "risk_level": 0.7,
                "feasibility": 0.5,
            },
            {
                "template": "creative",
                "description": "Creative approach",
                "actions": ["brainstorm for {situation}", "try novel approach"],
                "pros": ["innovative outcome"],
                "cons": ["uncertain payoff"],
                "risk_level": 0.5,
                "feasibility": 0.4,
            },
        ]

    def _generate_choice_description(self, template: str, situation: str, index: int) -> str:
        return f"Option {index + 1} ({template}): handle '{situation}' with this approach"

    def _generate_choice_reasoning(self, choice: Choice, situation: str) -> str:
        return f"Choice '{choice.description}' for situation '{situation}' has score {choice.score:.2f}"

    def score_choices(
        self,
        choices: List[Choice],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Choice]:
        with self._lock:
            for ch in choices:
                feasibility = float(ch.feasibility)
                risk = float(ch.risk_level)
                weight = float(self._autonomy_level)
                base = feasibility * 0.55 + (1.0 - risk) * 0.30 + weight * 0.15
                ch.score = max(0.0, min(1.0, base))
                if ch.status == ChoiceStatus.PENDING:
                    ch.status = ChoiceStatus.EVALUATED
            return list(choices)

    def make_decision(
        self,
        situation: str,
        goals: Optional[List[str]] = None,
        constraints: Optional[List[str]] = None,
        decision_type: Optional[DecisionType] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        with self._lock:
            ctx = DecisionContext(
                context_id=_new_id("ctx_"),
                situation=situation or "",
                goals=list(goals or []),
                constraints=list(constraints) if constraints else list(self._constraints),
            )
            if self._autonomy_level < 0.4:
                n_choices = 2
            elif self._autonomy_level < 0.75:
                n_choices = 3
            else:
                n_choices = 4
            choices = self.generate_choices(situation, num_choices=n_choices, context=context)
            self.score_choices(choices, context=context)
            choices_sorted = sorted(choices, key=lambda c: float(c.score), reverse=True)
            selected = choices_sorted[0] if choices_sorted else None
            if selected is not None:
                selected.status = ChoiceStatus.SELECTED
            if decision_type is None:
                decision_type = self._infer_decision_type(situation)
            reasoning = self._generate_decision_reasoning(selected, situation, goals or [])
            confidence = float(selected.score) if selected else 0.0
            decision = Decision(
                decision_id=_new_id("dec_"),
                decision_type=decision_type,
                context=ctx,
                choices=choices_sorted,
                selected_choice=selected,
                reasoning=reasoning,
                confidence=confidence,
            )
            self._add_to_history(decision)
            return decision

    def _infer_decision_type(self, situation: str) -> DecisionType:
        text = (situation or "").lower()
        if any(kw in text for kw in ("emergency", "urgent", "shutdown", "critical", "fire", "outage")):
            return DecisionType.EMERGENCY
        if any(kw in text for kw in ("strategy", "long-term", "roadmap", "vision")):
            return DecisionType.STRATEGIC
        if any(kw in text for kw in ("creative", "poem", "story", "imagine", "design a")):
            return DecisionType.CREATIVE
        if any(kw in text for kw in ("ethical", "moral", "right", "wrong", "should we")):
            return DecisionType.ETHICAL
        if any(kw in text for kw in ("tactic", "step by step", "approach to")):
            return DecisionType.TACTICAL
        return DecisionType.ROUTINE

    def _generate_decision_reasoning(
        self,
        choice: Optional[Choice],
        situation: str,
        goals: List[str],
    ) -> str:
        if choice is None:
            return f"No viable choice for situation '{situation}'."
        goals_text = ", ".join(goals) if goals else "unspecified goals"
        return (
            f"Selected '{choice.description}' for situation '{situation}' "
            f"to meet goals: {goals_text}. Score={choice.score:.2f}."
        )

    def can_act_autonomously(
        self,
        action: str,
        risk_level: float = 0.0,
        decision_type: Optional[str] = None,
    ) -> bool:
        with self._lock:
            risk = max(0.0, min(1.0, float(risk_level)))
            threshold = float(self._autonomy_level)
            dtype = (decision_type or "").lower() if isinstance(decision_type, str) else ""
            if dtype == DecisionType.EMERGENCY.value:
                threshold = float(self._autonomy_level) * 0.5
            elif dtype in (DecisionType.STRATEGIC.value, DecisionType.ETHICAL.value):
                threshold = float(self._autonomy_level) * 0.8
            elif dtype == DecisionType.CREATIVE.value:
                threshold = float(self._autonomy_level) * 0.9
            return risk <= threshold

    def should_refuse_request(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        decision = self.evaluate_action(action=action, context=context or {})
        return not bool(decision.get("allowed", True))

    def evaluate_action(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = (action or "").lower()
        is_risky = any(kw in text for kw in _RISKY_ACTION_KEYWORDS)

        if self._constraints:
            for c in self._constraints:
                ctext = c.lower()
                cleaned = ctext.replace("no_", "").replace("_", " ").strip()
                tokens = [t for t in cleaned.split() if t]
                if any(t in text for t in tokens):
                    return {
                        "allowed": False,
                        "reason": f"Action '{action}' blocked by constraint '{c}'",
                        "constraint": c,
                    }

        if is_risky:
            return {
                "allowed": False,
                "reason": f"Action '{action}' is risky and blocked by safety constraint",
                "constraint": "safety",
            }

        return {
            "allowed": True,
            "reason": "Action permitted under current autonomy policy",
            "constraint": None,
        }

    def update_preference(
        self,
        category: str,
        value: Any,
        weight: float = 0.5,
        description: str = "",
    ) -> bool:
        with self._lock:
            cat = str(category)
            now = time.time()
            w = max(0.0, min(1.0, float(weight)))
            existing = self._preferences.get(cat)
            if existing is not None:
                existing.value = value
                existing.weight = w
                if description:
                    existing.description = description
                existing.updated_at = now
            else:
                self._preferences[cat] = AgentPreference(
                    preference_id=_new_id("pref_"),
                    category=cat,
                    value=value,
                    weight=w,
                    description=description or "",
                )
            if self._dir is not None:
                self._save_preferences()
            self.emit_event(
                "autonomy.preference_updated",
                {"category": cat, "weight": w},
            )
            return True

    def add_custom_preference(
        self,
        category: str,
        value: Any,
        weight: float = 0.5,
        description: str = "",
    ) -> Optional[Dict[str, Any]]:
        self.update_preference(
            category=category,
            value=value,
            weight=weight,
            description=description,
        )
        return self.get_preference(category)

    def get_preference(self, category: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            pref = self._preferences.get(str(category))
            if pref is None:
                return None
            return self._pref_to_dict(pref)

    def get_all_preferences(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._pref_to_dict(p) for p in self._preferences.values()]

    @staticmethod
    def _pref_to_dict(pref: AgentPreference) -> Dict[str, Any]:
        return {
            "category": pref.category,
            "value": pref.value,
            "weight": float(pref.weight),
            "description": pref.description,
            "metadata": dict(pref.metadata),
            "created_at": float(pref.created_at),
            "updated_at": float(pref.updated_at),
        }

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        lessons: Optional[List[str]] = None,
    ) -> bool:
        with self._lock:
            for entry in reversed(self._decision_history):
                if entry.get("decision_id") == decision_id:
                    entry["outcome"] = str(outcome)
                    if lessons:
                        existing = entry.get("lessons_learned", [])
                        if not isinstance(existing, list):
                            existing = []
                        entry["lessons_learned"] = list(existing) + list(lessons)
                    else:
                        entry.setdefault("lessons_learned", [])
                    if self._dir is not None:
                        self._save_history()
                    self.emit_event(
                        "autonomy.outcome_recorded",
                        {"decision_id": decision_id, "outcome": outcome},
                    )
                    return True
            return False

    def get_decision_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._decision_history]

    def get_autonomy_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._decision_history)
            with_outcomes = sum(1 for d in self._decision_history if d.get("outcome"))
            by_type: Dict[str, int] = {}
            for d in self._decision_history:
                t = d.get("decision_type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1
            return {
                "total_decisions": total,
                "decisions_with_outcomes": with_outcomes,
                "autonomy_level": float(self._autonomy_level),
                "preference_count": len(self._preferences),
                "constraint_count": len(self._constraints),
                "by_type": by_type,
            }

    def _add_to_history(self, decision: Decision) -> None:
        with self._lock:
            self._decision_history.append(decision.to_dict())
            if self._dir is not None:
                self._save_history()
            self.emit_event("autonomy.decision_made", decision.to_dict())

    def _learn_from_feedback(self, decision: Decision, feedback: Dict[str, Any]) -> None:
        if not isinstance(feedback, dict):
            return
        outcome = feedback.get("outcome")
        if outcome == "successful":
            for ch in decision.choices:
                if ch.status == ChoiceStatus.SELECTED:
                    ch.metadata["validated"] = True
        self._add_to_history(decision)

    def _handle_evaluate_situation(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        result = self.evaluate_situation(
            situation=payload.get("situation", ""),
            goals=payload.get("goals"),
            context=payload.get("context"),
        )
        self.emit_event("autonomy.situation_evaluated", result)

    def _handle_make_decision(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        decision = self.make_decision(
            situation=payload.get("situation", ""),
            goals=payload.get("goals"),
            constraints=payload.get("constraints"),
        )
        self.emit_event("autonomy.decision_made", decision.to_dict())

    def _handle_set_preference(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        self.update_preference(
            category=payload.get("category", ""),
            value=payload.get("value"),
            weight=float(payload.get("weight", 0.5)),
            description=payload.get("description", ""),
        )

    def _save_all(self) -> None:
        self._save_state()
        self._save_preferences()
        self._save_history()
        self._save_constraints()

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        try:
            payload = {
                "module_id": self.MODULE_ID,
                "module_version": self.MODULE_VERSION,
                "autonomy_level": float(self._autonomy_level),
                "updated_at": _now_iso(),
            }
            self._state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save autonomy state: %s", exc)

    def _save_preferences(self) -> None:
        if self._prefs_path is None:
            return
        try:
            payload = {cat: pref.to_dict() for cat, pref in self._preferences.items()}
            self._prefs_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save preferences: %s", exc)

    def _save_history(self) -> None:
        if self._history_path is None:
            return
        try:
            payload = {"items": list(self._decision_history)}
            self._history_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save history: %s", exc)

    def _save_constraints(self) -> None:
        if self._constraints_path is None:
            return
        try:
            payload = {"items": list(self._constraints), "updated_at": _now_iso()}
            self._constraints_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save constraints: %s", exc)

    def _load(self) -> None:
        if self._dir is None:
            return
        try:
            if self._state_path and self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._autonomy_level = max(
                        0.0,
                        min(1.0, float(data.get("autonomy_level", self._autonomy_level))),
                    )
            if self._prefs_path and self._prefs_path.exists():
                data = json.loads(self._prefs_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    loaded: Dict[str, AgentPreference] = {}
                    for k, v in data.items():
                        if isinstance(v, dict):
                            try:
                                loaded[str(k)] = AgentPreference.from_dict(v)
                            except (KeyError, TypeError, ValueError):
                                continue
                    if loaded:
                        self._preferences = loaded
            if self._history_path and self._history_path.exists():
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    self._decision_history = [dict(x) for x in data["items"] if isinstance(x, dict)]
            if self._constraints_path and self._constraints_path.exists():
                data = json.loads(self._constraints_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    self._constraints = [str(x) for x in data["items"]]
        except Exception as exc:
            logger.warning("Failed to load autonomy state: %s", exc)


_singleton: Optional[AgentAutonomySystem] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/autonomy_system"


def get_autonomy_system(storage_dir: Optional[str] = None) -> AgentAutonomySystem:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            target = storage_dir or _DEFAULT_DIR
            Path(target).mkdir(parents=True, exist_ok=True)
            _singleton = AgentAutonomySystem(storage_dir=target)
    return _singleton


def reset_autonomy_system() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "AgentAutonomySystem",
    "AgentPreference",
    "Choice",
    "ChoiceStatus",
    "Decision",
    "DecisionContext",
    "DecisionType",
    "get_autonomy_system",
    "reset_autonomy_system",
]
