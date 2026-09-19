"""判据三态契约（工单 003）。

RSI 的晋升与停止判据此前只有二态。于是"取不到判据所需数据"被编码成
"数据等于 0 / 等于空串"，再顺着 `if` 走下去 —— 与"证据确凿地通过"不可区分。
实测三处都是这个形状：

- `orchestrator.py:176-184` 无回滚历史时返回 `0.0`，把"没发生过回滚"
  与"回滚证据缺失"压成同一个值，于是 1→2 的 7 天判据永远不可满足；
- `orchestrator.py:261-264` 读一个 `analyze_convergence()` 从不产出的 `roi` 键
  并兜底成 0.0，使 `roi < 0` 守卫在有负 ROI 时照样放行；
- `rsi/dashboard.py:136-138` 直接 `return []` 并注释"暂时"。

本模块给出共享的三态表达。**关键约束是 `__bool__` 只在 `passed` 时为真**：
调用方沿用 `if verdict:` 的写法就天然不会把"没证据"当"通过"，
无需在每个调用点各写一次判空（那正是本项目修复教义禁止的 consumer-only guard）。

判定请写 `if verdict:` 或 `verdict.state`；本类不提供与工厂方法同名的实例属性，
避免 `GateVerdict.passed(...)` 构造与 `verdict.passed` 读取两套语义互相遮蔽。

术语约定（`docs/CONTEXT.md`）：
- `unevidenced`：判据所需数据取不到。不得按 passed 处理，且必须出现在观测面。
- `measurement_blind`：`unevidenced` 的特例，专指"评测用例因参数回退到 setpoint
  而失去区分力"。由工单 007 产生，008/009 消费；与本态不可混用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

STATE_PASSED = "passed"
STATE_FAILED = "failed"
STATE_UNEVIDENCED = "unevidenced"
_VERDICT_STATES = (STATE_PASSED, STATE_FAILED, STATE_UNEVIDENCED)


@dataclass(frozen=True)
class GateVerdict:
    """一条判据的结论。

    构造请走三个类方法 —— 它们保证非 `passed` 时 `reason` 必填，
    杜绝"无理由的未知"再次退化成静默通过。
    """

    STATE_PASSED: ClassVar[str] = STATE_PASSED
    STATE_FAILED: ClassVar[str] = STATE_FAILED
    STATE_UNEVIDENCED: ClassVar[str] = STATE_UNEVIDENCED

    state: str = STATE_PASSED
    reason: str = ""
    evidence: Optional[Any] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.state not in _VERDICT_STATES:
            raise ValueError(
                f"非法判据状态 {self.state!r}，只接受 {_VERDICT_STATES}；"
                "新增状态须同步所有消费方，不得就地自造"
            )
        if self.state != STATE_PASSED and not str(self.reason).strip():
            raise ValueError(
                f"{self.state} 判据必须写明 reason，否则又变成一次无人能解释的降级"
            )

    def __bool__(self) -> bool:
        return self.state == STATE_PASSED

    @classmethod
    def passed(cls, reason: str = "", evidence: Any = None) -> "GateVerdict":
        return cls(state=STATE_PASSED, reason=reason, evidence=evidence)

    @classmethod
    def failed(cls, reason: str, evidence: Any = None) -> "GateVerdict":
        return cls(state=STATE_FAILED, reason=reason, evidence=evidence)

    @classmethod
    def unevidenced(cls, reason: str, evidence: Any = None) -> "GateVerdict":
        return cls(state=STATE_UNEVIDENCED, reason=reason, evidence=evidence)

    @classmethod
    def of(cls, state: str, reason: str = "", evidence: Any = None) -> "GateVerdict":
        """从外部数据（如已序列化的判据）还原，供端点与摘要面使用。"""
        return cls(state=state, reason=reason, evidence=evidence)

    def to_dict(self) -> dict:
        return {"state": self.state, "reason": self.reason, "evidence": self.evidence}
