"""世代账本（P0-3）—— 递归自进化「时间递归」的载体。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§2.3（世代模型）/ §3.2（generation_ledger 完整设计）/ §6 P0-3。

世代（``EvolutionGeneration``）是跨臂代际因果的唯一记账单元：
为什么改（``signals``）、改了什么（``changes``）、各门禁三态结论
（``verdicts``）、裁决（``decision``）、部署与回滚（``deployment``）。
RSI 既有的回执/指标/摘要继续各司其职，本账本不复制它们的数据。

状态机（转移合法性单源 ``_ACTION_TRANSITIONS``，纪律沿
``neurova/evolution/proposal_lifecycle.py``：非法转移抛错点名当前态与期望态，
不静默）::

    proposed → shadowTesting → gated → canary → deployed
        ↘ rejected（任一未部署环节可拒，留档）
    deployed → rolledBack（留档）

rejected / rolledBack 是终态：只留档，不再转移。

持久化：落盘路径由 env ``NEUROVA_EVOLUTION_GENERATIONS`` 指定；未配置时
纯内存零 IO（沿 ``rsi/rollback_manager`` 的 ``ROLLBACK_STATE_ENV`` 同款约定，
防止几十个单测把仓库 data/ 变成状态污染源）。写入原子（tmp + os.replace）；
落盘文件损坏时回退空态并告警，不阻断进程启动。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.gate_verdict import GateVerdict

logger = get_logger(__name__)

__all__ = [
    "DECISION_KINDS",
    "GENERATIONS_STATE_ENV",
    "ChangeRef",
    "DecisionRef",
    "DeploymentRef",
    "EvolutionGeneration",
    "GenerationLedger",
    "GenerationStatus",
    "GenerationTransitionError",
    "SignalRef",
    "resolveGenerationsStatePath",
]

_PAYLOAD_VERSION = 1

# 世代账本落盘路径开关。未显式设置时不做任何 IO ——
# 与 NEUROVA_EVOLUTION_ROLLBACK / NEUROVA_EVOLUTION_RSI_SUMMARIES 同款约定。
GENERATIONS_STATE_ENV = "NEUROVA_EVOLUTION_GENERATIONS"


def resolveGenerationsStatePath() -> Optional[Path]:
    """世代账本落盘路径；未配置环境变量时返回 None（调用方据此零 IO）。"""
    env_path = os.environ.get(GENERATIONS_STATE_ENV)
    return Path(env_path) if env_path else None


def _utcNowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenerationStatus(str, Enum):
    """世代状态（规范值）。状态机见模块 docstring。"""

    PROPOSED = "proposed"
    SHADOW_TESTING = "shadowTesting"
    GATED = "gated"
    CANARY = "canary"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolledBack"


class GenerationTransitionError(ValueError):
    """非法世代状态转移、非法状态值或非法世代引用。"""


_STATUS_ORDER = (
    GenerationStatus.PROPOSED,
    GenerationStatus.SHADOW_TESTING,
    GenerationStatus.GATED,
    GenerationStatus.CANARY,
    GenerationStatus.DEPLOYED,
    GenerationStatus.REJECTED,
    GenerationStatus.ROLLED_BACK,
)

# 转移合法性单源：动作 → {合法发起态: 落定态}。
# 新增转移只许改这张表并同步其消费方，不许在调用点各写各的 if。
_ACTION_TRANSITIONS: Dict[str, Dict[GenerationStatus, GenerationStatus]] = {
    # 落判据：首批判据落账即进入影子验证；门禁链结论齐备即完成 gating
    "recordVerdicts": {
        GenerationStatus.PROPOSED: GenerationStatus.SHADOW_TESTING,
        GenerationStatus.SHADOW_TESTING: GenerationStatus.GATED,
    },
    # 裁决放行：门禁齐备后 auto/approval 决定进入金丝雀观测
    "recordDecision": {GenerationStatus.GATED: GenerationStatus.CANARY},
    # 晋升：金丝雀观测窗通过 → 部署生产
    "markDeployed": {GenerationStatus.CANARY: GenerationStatus.DEPLOYED},
    # 拒绝：任一未部署环节可拒，留档
    "markRejected": {
        GenerationStatus.PROPOSED: GenerationStatus.REJECTED,
        GenerationStatus.SHADOW_TESTING: GenerationStatus.REJECTED,
        GenerationStatus.GATED: GenerationStatus.REJECTED,
        GenerationStatus.CANARY: GenerationStatus.REJECTED,
    },
    # 回滚：仅已部署代可回滚，留档
    "markRolledBack": {GenerationStatus.DEPLOYED: GenerationStatus.ROLLED_BACK},
}


def _requireTransition(current: str, action: str) -> str:
    """校验 action 可从 current 发起，返回落定态；非法转移点名报错。"""
    table = _ACTION_TRANSITIONS[action]
    target = table.get(current)
    if target is None:
        if current not in _STATUS_ORDER:
            raise GenerationTransitionError(f"非法世代状态: {current!r}")
        expected = "、".join(s.value for s in _STATUS_ORDER if s in table)
        raise GenerationTransitionError(
            f"非法状态转移：当前状态 {current}，{action} 仅允许从 {expected} 态发起"
        )
    return target.value


DECISION_KINDS = ("auto", "approval", "rejected")


@dataclass(frozen=True)
class SignalRef:
    """一条「为什么改」的信号引用（教训/评测失败/反馈/守卫）。"""

    kind: str
    ref: str = ""
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "summary": self.summary}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SignalRef":
        return cls(
            kind=str(raw.get("kind", "")),
            ref=str(raw.get("ref", "")),
            summary=str(raw.get("summary", "")),
        )


@dataclass(frozen=True)
class ChangeRef:
    """一条「改了什么」的变更引用（targetId + 补丁/参数引用 + 理由）。"""

    targetId: str
    kind: str = ""
    ref: str = ""
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "targetId": self.targetId,
            "kind": self.kind,
            "ref": self.ref,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ChangeRef":
        return cls(
            targetId=str(raw.get("targetId", "")),
            kind=str(raw.get("kind", "")),
            ref=str(raw.get("ref", "")),
            rationale=str(raw.get("rationale", "")),
        )


@dataclass(frozen=True)
class DecisionRef:
    """裁决引用：auto / approval(approver) / rejected(reason)。

    approval 必须记录非空审批人（人类评审主 gate，沿 proposal_lifecycle 纪律）；
    rejected 必须写明 reason，杜绝无理由的否决。
    """

    kind: str
    approver: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in DECISION_KINDS:
            raise ValueError(
                f"非法裁决类型 {self.kind!r}，只接受 {DECISION_KINDS}"
            )
        if self.kind == "approval" and not self.approver.strip():
            raise ValueError("approval 裁决必须记录非空审批人（人类评审主 gate）")
        if self.kind == "rejected" and not self.reason.strip():
            raise ValueError("rejected 裁决必须写明 reason")

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "approver": self.approver, "reason": self.reason}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DecisionRef":
        return cls(
            kind=str(raw.get("kind", "")),
            approver=str(raw.get("approver", "")),
            reason=str(raw.get("reason", "")),
        )


@dataclass(frozen=True)
class DeploymentRef:
    """部署引用：金丝雀观测结论 / 晋升时刻 / 回滚落点。"""

    promotedAt: str = ""
    canaryConclusion: str = ""
    rolledBackTo: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "promotedAt": self.promotedAt,
            "canaryConclusion": self.canaryConclusion,
            "rolledBackTo": self.rolledBackTo,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DeploymentRef":
        rolled_back_to = raw.get("rolledBackTo")
        return cls(
            promotedAt=str(raw.get("promotedAt", "")),
            canaryConclusion=str(raw.get("canaryConclusion", "")),
            rolledBackTo=None if rolled_back_to is None else int(rolled_back_to),
        )


@dataclass
class EvolutionGeneration:
    """一代演化尝试的完整档案（谱系主键 generationNo）。"""

    generationNo: int
    parentNo: Optional[int]
    basisCommit: str
    createdAt: str
    signals: List[SignalRef] = field(default_factory=list)
    changes: List[ChangeRef] = field(default_factory=list)
    verdicts: Dict[str, GateVerdict] = field(default_factory=dict)
    decision: Optional[DecisionRef] = None
    deployment: Optional[DeploymentRef] = None
    status: str = GenerationStatus.PROPOSED.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generationNo": self.generationNo,
            "parentNo": self.parentNo,
            "basisCommit": self.basisCommit,
            "createdAt": self.createdAt,
            "signals": [s.to_dict() for s in self.signals],
            "changes": [c.to_dict() for c in self.changes],
            "verdicts": {k: v.to_dict() for k, v in self.verdicts.items()},
            "decision": self.decision.to_dict() if self.decision is not None else None,
            "deployment": self.deployment.to_dict() if self.deployment is not None else None,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "EvolutionGeneration":
        verdicts_raw = raw.get("verdicts") or {}
        decision_raw = raw.get("decision")
        deployment_raw = raw.get("deployment")
        return cls(
            generationNo=int(raw["generationNo"]),
            parentNo=None if raw.get("parentNo") is None else int(raw["parentNo"]),
            basisCommit=str(raw.get("basisCommit", "")),
            createdAt=str(raw.get("createdAt", "")),
            signals=[_coerceSignal(s) for s in (raw.get("signals") or [])],
            changes=[_coerceChange(c) for c in (raw.get("changes") or [])],
            verdicts={str(k): _coerceVerdict(v) for k, v in verdicts_raw.items()},
            decision=None if decision_raw is None else _coerceDecision(decision_raw),
            deployment=(
                None if deployment_raw is None else _coerceDeployment(deployment_raw)
            ),
            status=str(raw.get("status", GenerationStatus.PROPOSED.value)),
        )


def _coerceSignal(raw: Any) -> SignalRef:
    if isinstance(raw, SignalRef):
        return raw
    if isinstance(raw, dict):
        return SignalRef.from_dict(raw)
    raise ValueError(f"非法信号引用载荷: {raw!r}")


def _coerceChange(raw: Any) -> ChangeRef:
    if isinstance(raw, ChangeRef):
        return raw
    if isinstance(raw, dict):
        return ChangeRef.from_dict(raw)
    raise ValueError(f"非法变更引用载荷: {raw!r}")


def _coerceVerdict(raw: Any) -> GateVerdict:
    if isinstance(raw, GateVerdict):
        return raw
    if isinstance(raw, dict):
        return GateVerdict.of(
            state=str(raw.get("state", GateVerdict.STATE_PASSED)),
            reason=str(raw.get("reason", "")),
            evidence=raw.get("evidence"),
        )
    raise ValueError(f"非法判据载荷: {raw!r}")


def _coerceDecision(raw: Any) -> DecisionRef:
    if isinstance(raw, DecisionRef):
        return raw
    if isinstance(raw, dict):
        return DecisionRef.from_dict(raw)
    raise ValueError(f"非法裁决载荷: {raw!r}")


def _coerceDeployment(raw: Any) -> DeploymentRef:
    if isinstance(raw, DeploymentRef):
        return raw
    if isinstance(raw, dict):
        return DeploymentRef.from_dict(raw)
    raise ValueError(f"非法部署载荷: {raw!r}")


class GenerationLedger:
    """跨臂代际因果账本。

    线程安全（RLock）；落盘行为见模块 docstring：env 未配置时纯内存零 IO，
    配置后每次变更原子落盘，损坏文件回退空态不阻断。
    """

    def __init__(self, *, statePath: Optional[Path] = None):
        self._lock = threading.RLock()
        self._statePath = (
            statePath if statePath is not None else resolveGenerationsStatePath()
        )
        self._generations: Dict[int, EvolutionGeneration] = {}
        self._load()

    # ── 开代与查询 ────────────────────────────────────────────

    def openGeneration(
        self,
        parentNo: Optional[int],
        signals: Optional[Iterable[Any]],
        changes: Optional[Iterable[Any]],
        basisCommit: str,
    ) -> EvolutionGeneration:
        """开启新一代：status=proposed，世代序号自增；parentNo 必须可解析。"""
        with self._lock:
            if parentNo is not None and int(parentNo) not in self._generations:
                raise ValueError(f"父代 {parentNo} 不存在于账本，谱系引用必须可解析")
            gen = EvolutionGeneration(
                generationNo=self._nextNo(),
                parentNo=None if parentNo is None else int(parentNo),
                basisCommit=str(basisCommit or ""),
                createdAt=_utcNowIso(),
                signals=[_coerceSignal(s) for s in (signals or [])],
                changes=[_coerceChange(c) for c in (changes or [])],
            )
            self._generations[gen.generationNo] = gen
            self._persist()
            return gen

    def get(self, generationNo: int) -> Optional[EvolutionGeneration]:
        """按序号取代；不存在返回 None（查询面不抛）。"""
        with self._lock:
            return self._generations.get(int(generationNo))

    def currentBaseline(self) -> Optional[EvolutionGeneration]:
        """当前生产基线 = 序号最大的 deployed 代；尚无部署返回 None（不编造）。"""
        with self._lock:
            deployed = [
                g
                for g in self._generations.values()
                if g.status == GenerationStatus.DEPLOYED.value
            ]
            if not deployed:
                return None
            return max(deployed, key=lambda g: g.generationNo)

    def lineage(self, generationNo: int) -> List[EvolutionGeneration]:
        """从指定代起向上回溯父链（含自身），直到根代；环引用截断防死循环。"""
        with self._lock:
            chain: List[EvolutionGeneration] = []
            seen = set()
            cursor = self._require(generationNo)
            while cursor is not None and cursor.generationNo not in seen:
                seen.add(cursor.generationNo)
                chain.append(cursor)
                cursor = (
                    self._generations.get(cursor.parentNo)
                    if cursor.parentNo is not None
                    else None
                )
            return chain

    def listAll(self) -> List[EvolutionGeneration]:
        """全部世代按序号升序（P1-5 治理读面的只读访问器；查询面不抛）。

        P0-3 的账本接口只有逐代 get / 基线 / 谱系，列表读面（governance
        GET /rsi/generations）需要一个全量枚举口——最小追加，不改任何
        状态转移逻辑。
        """
        with self._lock:
            return [self._generations[no] for no in sorted(self._generations)]

    # ── 状态转移 ──────────────────────────────────────────────

    def recordVerdicts(self, generationNo: int, verdicts: Dict[str, Any]) -> None:
        """落账门禁三态结论：proposed→shadowTesting（影子判据），再→gated（门禁链齐备）。"""
        if not verdicts:
            raise ValueError("recordVerdicts 必须携带至少一条判据，空落账即无声降级")
        with self._lock:
            gen = self._require(generationNo)
            target = _requireTransition(gen.status, "recordVerdicts")
            for name, verdict in verdicts.items():
                gen.verdicts[str(name)] = _coerceVerdict(verdict)
            gen.status = target
            self._persist()

    def recordDecision(self, generationNo: int, decision: Any) -> None:
        """落账裁决：gated→canary（auto/approval 放行进金丝雀）。

        kind=rejected 的裁决统一路由到 markRejected 通道（单一事实源）。
        """
        with self._lock:
            gen = self._require(generationNo)
            ref = _coerceDecision(decision)
            if ref.kind == "rejected":
                self._markRejectedLocked(gen, ref.reason or "裁决拒绝")
                return
            target = _requireTransition(gen.status, "recordDecision")
            gen.decision = ref
            gen.status = target
            self._persist()

    def markDeployed(self, generationNo: int, deployment: Any) -> None:
        """晋升生产：canary→deployed；未给 promotedAt 时自动补当前时刻。"""
        with self._lock:
            gen = self._require(generationNo)
            ref = _coerceDeployment(deployment)
            target = _requireTransition(gen.status, "markDeployed")
            if not ref.promotedAt:
                ref = replace(ref, promotedAt=_utcNowIso())
            gen.deployment = ref
            gen.status = target
            self._persist()

    def markRejected(self, generationNo: int, reason: str) -> None:
        """拒绝留档：任一未部署环节可发起；必须写明理由。"""
        if not str(reason or "").strip():
            raise ValueError("拒绝必须写明 reason，否则又变成一次无人能解释的降级")
        with self._lock:
            gen = self._require(generationNo)
            self._markRejectedLocked(gen, str(reason))

    def markRolledBack(self, generationNo: int, restoredTo: int) -> None:
        """部署后回滚留档：deployed→rolledBack，记录回滚落点 restoredTo。"""
        with self._lock:
            gen = self._require(generationNo)
            target = _requireTransition(gen.status, "markRolledBack")
            if int(restoredTo) not in self._generations:
                raise ValueError(f"回滚目标世代 {restoredTo} 不存在于账本")
            if int(restoredTo) == gen.generationNo:
                raise ValueError("回滚目标不能是当前世代自身")
            base = gen.deployment if gen.deployment is not None else DeploymentRef()
            gen.deployment = replace(base, rolledBackTo=int(restoredTo))
            gen.status = target
            self._persist()

    # ── 内部 ──────────────────────────────────────────────────

    def _markRejectedLocked(self, gen: EvolutionGeneration, reason: str) -> None:
        """拒绝落账（锁内）；decision 与 status 一并落，留档可归因。"""
        target = _requireTransition(gen.status, "markRejected")
        gen.decision = DecisionRef(kind="rejected", reason=reason)
        gen.status = target
        self._persist()

    def _require(self, generationNo: int) -> EvolutionGeneration:
        gen = self._generations.get(int(generationNo))
        if gen is None:
            raise KeyError(f"世代 {generationNo} 不存在于账本")
        return gen

    def _nextNo(self) -> int:
        return max(self._generations, default=0) + 1

    def _persist(self) -> None:
        """原子落盘（tmp + os.replace）；未配置路径时零 IO。失败告警不抛。"""
        if self._statePath is None:
            return
        payload = {
            "version": _PAYLOAD_VERSION,
            "generations": [
                self._generations[no].to_dict() for no in sorted(self._generations)
            ],
        }
        try:
            tmp = self._statePath.with_suffix(self._statePath.suffix + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self._statePath)
        except OSError as exc:
            logger.warning(
                "世代账本落盘失败(%s): %s", self._statePath, exc
            )

    def _load(self) -> None:
        """启动读回；文件缺失/损坏/结构不符一律回退空态，不阻断进程。"""
        if self._statePath is None or not self._statePath.exists():
            return
        try:
            raw = json.loads(self._statePath.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("世代账本落盘结构不是对象")
            for item in raw.get("generations", []):
                gen = EvolutionGeneration.from_dict(item)
                self._generations[gen.generationNo] = gen
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "世代账本落盘文件损坏，回退空态不阻断: %s (%s)", self._statePath, exc
            )
            self._generations.clear()
