"""广告自动调优的动作闸门：预算/出价上限、幂等账本与审计流水。

设计边界：
- **只读永远放行**；写操作先过硬上限（超限直接拒绝，不看开关），再过武装开关
  （`NEUROVA_ADS_AUTO_APPLY=1` 才允许无人执行；未武装时返回 approval_required）。
- 同一个动作在一个去重窗口内只允许落地一次，重放返回 duplicate 而不是再写一遍。
- 每次落地都写审计流水，含前值、后值、依据与时间；审计失败不阻断执行但会带 warn。

闸门是"花钱动作"的最后一道防线，宁可拒绝也不猜。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_DAILY_BUDGET = 2000.0
DEFAULT_MIN_DAILY_BUDGET = 1.0
DEFAULT_MAX_BUDGET_INCREASE_RATIO = 0.30
DEFAULT_MAX_BUDGET_DECREASE_RATIO = 0.50
DEFAULT_MAX_BID = 50.0
DEFAULT_MIN_BID = 0.02
DEFAULT_MAX_BID_INCREASE_RATIO = 0.20
DEFAULT_MAX_BID_DECREASE_RATIO = 0.50
DEFAULT_MAX_ACTIONS_PER_RUN = 5
DEFAULT_MAX_ACTIONS_PER_DAY = 2
DEFAULT_DEDUPE_WINDOW_SECONDS = 3600

_ALLOWED_CAMPAIGN_STATES = frozenset({"ENABLED", "PAUSED"})


def _envBool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _envFloat(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _envInt(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _asFloat(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class AdActionPolicy:
    """一次写操作的准入策略（从环境变量读取，测试可显式构造）。"""

    auto_apply: bool = False
    max_daily_budget: float = DEFAULT_MAX_DAILY_BUDGET
    min_daily_budget: float = DEFAULT_MIN_DAILY_BUDGET
    max_budget_increase_ratio: float = DEFAULT_MAX_BUDGET_INCREASE_RATIO
    max_budget_decrease_ratio: float = DEFAULT_MAX_BUDGET_DECREASE_RATIO
    max_bid: float = DEFAULT_MAX_BID
    min_bid: float = DEFAULT_MIN_BID
    max_bid_increase_ratio: float = DEFAULT_MAX_BID_INCREASE_RATIO
    max_bid_decrease_ratio: float = DEFAULT_MAX_BID_DECREASE_RATIO
    max_actions_per_run: int = DEFAULT_MAX_ACTIONS_PER_RUN
    max_actions_per_day: int = DEFAULT_MAX_ACTIONS_PER_DAY

    @classmethod
    def fromEnv(cls) -> "AdActionPolicy":
        return cls(
            auto_apply=_envBool("NEUROVA_ADS_AUTO_APPLY", False),
            max_daily_budget=_envFloat("NEUROVA_ADS_MAX_DAILY_BUDGET", DEFAULT_MAX_DAILY_BUDGET),
            min_daily_budget=_envFloat("NEUROVA_ADS_MIN_DAILY_BUDGET", DEFAULT_MIN_DAILY_BUDGET),
            max_budget_increase_ratio=_envFloat(
                "NEUROVA_ADS_MAX_BUDGET_INCREASE_RATIO", DEFAULT_MAX_BUDGET_INCREASE_RATIO
            ),
            max_budget_decrease_ratio=_envFloat(
                "NEUROVA_ADS_MAX_BUDGET_DECREASE_RATIO", DEFAULT_MAX_BUDGET_DECREASE_RATIO
            ),
            max_bid=_envFloat("NEUROVA_ADS_MAX_BID", DEFAULT_MAX_BID),
            min_bid=_envFloat("NEUROVA_ADS_MIN_BID", DEFAULT_MIN_BID),
            max_bid_increase_ratio=_envFloat(
                "NEUROVA_ADS_MAX_BID_INCREASE_RATIO", DEFAULT_MAX_BID_INCREASE_RATIO
            ),
            max_bid_decrease_ratio=_envFloat(
                "NEUROVA_ADS_MAX_BID_DECREASE_RATIO", DEFAULT_MAX_BID_DECREASE_RATIO
            ),
            max_actions_per_run=_envInt(
                "NEUROVA_ADS_MAX_ACTIONS_PER_RUN", DEFAULT_MAX_ACTIONS_PER_RUN
            ),
            max_actions_per_day=_envInt(
                "NEUROVA_ADS_MAX_ACTIONS_PER_DAY", DEFAULT_MAX_ACTIONS_PER_DAY
            ),
        )

    def limits(self) -> Dict[str, Any]:
        return {
            "auto_apply": self.auto_apply,
            "max_daily_budget": self.max_daily_budget,
            "min_daily_budget": self.min_daily_budget,
            "max_budget_increase_ratio": self.max_budget_increase_ratio,
            "max_budget_decrease_ratio": self.max_budget_decrease_ratio,
            "max_bid": self.max_bid,
            "min_bid": self.min_bid,
            "max_bid_increase_ratio": self.max_bid_increase_ratio,
            "max_bid_decrease_ratio": self.max_bid_decrease_ratio,
            "max_actions_per_run": self.max_actions_per_run,
            "max_actions_per_day": self.max_actions_per_day,
        }

    def evaluate(self, action: str, before: Any, proposed: Any) -> Dict[str, Any]:
        """判定一次写操作：allow / deny / approval_required。

        硬上限（候选值本身非法）永远 deny；合法候选在未武装时要求审批。
        """
        reasons = []
        action = str(action or "").strip()

        if action in ("campaign_budget", "keyword_bid"):
            old = _asFloat(before)
            new = _asFloat(proposed)
            if old is None or new is None or old <= 0 or new <= 0:
                return self._decision("deny", ["前值与目标值必须是正数"], action)
            if abs(new - old) < 1e-9:
                return self._decision("deny", ["目标值与现值相同，无需写操作"], action)

            if action == "campaign_budget":
                if new > self.max_daily_budget:
                    reasons.append(
                        f"目标日预算 {new} 超过硬上限 {self.max_daily_budget}"
                    )
                if new < self.min_daily_budget:
                    reasons.append(
                        f"目标日预算 {new} 低于下限 {self.min_daily_budget}"
                    )
                if new > old and (new - old) / old > self.max_budget_increase_ratio:
                    reasons.append(
                        f"预算上调幅度 {(new - old) / old:.0%} 超过单次上限 "
                        f"{self.max_budget_increase_ratio:.0%}"
                    )
                if new < old and (old - new) / old > self.max_budget_decrease_ratio:
                    reasons.append(
                        f"预算下调幅度 {(old - new) / old:.0%} 超过单次上限 "
                        f"{self.max_budget_decrease_ratio:.0%}"
                    )
            else:
                if new > self.max_bid:
                    reasons.append(f"目标出价 {new} 超过硬上限 {self.max_bid}")
                if new < self.min_bid:
                    reasons.append(f"目标出价 {new} 低于下限 {self.min_bid}")
                if new > old and (new - old) / old > self.max_bid_increase_ratio:
                    reasons.append(
                        f"出价上调幅度 {(new - old) / old:.0%} 超过单次上限 "
                        f"{self.max_bid_increase_ratio:.0%}"
                    )
                if new < old and (old - new) / old > self.max_bid_decrease_ratio:
                    reasons.append(
                        f"出价下调幅度 {(old - new) / old:.0%} 超过单次上限 "
                        f"{self.max_bid_decrease_ratio:.0%}"
                    )
        elif action == "campaign_state":
            old = str(before or "").upper()
            new = str(proposed or "").upper()
            if new not in _ALLOWED_CAMPAIGN_STATES:
                reasons.append(f"活动状态 {new!r} 不在允许范围 {sorted(_ALLOWED_CAMPAIGN_STATES)}")
            if old == new:
                reasons.append("目标状态与现状态相同，无需写操作")
        else:
            reasons.append(f"未知动作类型: {action!r}")

        if reasons:
            return self._decision("deny", reasons, action)

        if not self.auto_apply:
            return self._decision(
                "approval_required",
                ["写操作未武装（NEUROVA_ADS_AUTO_APPLY 未开启），需人工审批"],
                action,
            )
        return self._decision("allow", [], action)

    @staticmethod
    def _decision(decision: str, reasons: list, action: str) -> Dict[str, Any]:
        return {"decision": decision, "reasons": reasons, "action": action}


class AdActionLedger:
    """动作账本：去重窗口 + 审计流水（JSON 原子写，线程安全）。"""

    def __init__(self, path: str = "", auditPath: str = ""):
        self.path = path or os.environ.get("NEUROVA_AD_ACTION_LEDGER") or dataPath(
            "ad_actions.json"
        )
        self.auditPath = auditPath or os.environ.get("NEUROVA_AD_ACTION_AUDIT") or dataPath(
            "ad_actions_audit.jsonl"
        )
        self._lock = threading.RLock()

    def key(self, payload: Dict[str, Any], windowSeconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS) -> str:
        window = max(1, int(windowSeconds or DEFAULT_DEDUPE_WINDOW_SECONDS))
        bucket = int(time.time() // window)
        canonical = json.dumps(
            {"bucket": bucket, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("广告动作账本读取失败，按空账本继续: %s", self.path)
            return {}

    def isApplied(self, key: str) -> bool:
        with self._lock:
            entries = self._read().get("entries") or {}
            return key in entries

    def countRecent(self, campaignId: str, windowSeconds: int = 86400) -> int:
        """统计同一活动在窗口内已落地的动作数（每日总量闸门的数据源）。"""
        since = time.time() - max(1, int(windowSeconds or 86400))
        with self._lock:
            entries = self._read().get("entries") or {}
        return sum(
            1
            for entry in entries.values()
            if isinstance(entry, dict)
            and str(entry.get("campaign_id") or "") == str(campaignId)
            and float(entry.get("recorded_at") or 0) >= since
        )

    def record(self, key: str, entry: Dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            entries = data.get("entries")
            if not isinstance(entries, dict):
                entries = {}
            entries[key] = {"recorded_at": time.time(), **(entry or {})}
            data["entries"] = entries
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, self.path)

    def audit(self, entry: Dict[str, Any]) -> None:
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.auditPath) or ".", exist_ok=True)
                with open(self.auditPath, "a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {"ts": time.time(), **(entry or {})},
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )
            except OSError as exc:
                logger.warning("广告动作审计写入失败（不阻断执行）: %s", exc)


__all__ = [
    "AdActionPolicy",
    "AdActionLedger",
    "DEFAULT_MAX_DAILY_BUDGET",
    "DEFAULT_MAX_BUDGET_INCREASE_RATIO",
    "DEFAULT_MAX_BID",
    "DEFAULT_MAX_BID_INCREASE_RATIO",
    "DEFAULT_MAX_ACTIONS_PER_RUN",
    "DEFAULT_DEDUPE_WINDOW_SECONDS",
]
