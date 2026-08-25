"""
统一治理策略中心 (对齐 QwenPaw Governance)。

将已有的工具护栏（ToolGuardEngine / ShellEvasionGuardian / FilePathGuardian）
收敛为统一的四级裁决：allow / deny / ask / sandbox。

- CRITICAL / 阻断级发现 → DENY
- HIGH → SANDBOX（默认）或 ASK（ask_on_high=True 时）
- 其余 → ALLOW
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.sandbox.exec_sandbox import SandboxSeverity, execute_in_sandbox
from neurova.security.tool_guard import ApprovalMode, GuardSeverity, ToolGuardEngine

logger = get_logger(__name__)


class GovernanceDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    SANDBOX = "sandbox"


@dataclass
class GovernanceResult:
    decision: GovernanceDecision
    reasons: List[str] = field(default_factory=list)
    severity: SandboxSeverity = SandboxSeverity.NONE
    findings: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "severity": self.severity.value,
            "finding_count": len(self.findings),
        }


class GovernancePolicy:
    """统一治理策略。"""

    def __init__(
        self,
        engine: Optional[ToolGuardEngine] = None,
        default_action: GovernanceDecision = GovernanceDecision.ALLOW,
        ask_on_high: bool = False,
        sandbox_severity: SandboxSeverity = SandboxSeverity.READ_ONLY,
        tool_overrides: Optional[Dict[str, GovernanceDecision]] = None,
        whitelist_entries: Optional[List[Dict[str, Any]]] = None,
        whitelist_path: Optional[Path] = None,
    ):
        self.engine = engine or ToolGuardEngine(ApprovalMode.AUTO)
        self.default_action = default_action
        self.ask_on_high = ask_on_high
        self.sandbox_severity = sandbox_severity
        # 方案 1.5: 按工具维度覆盖策略（如 run_code -> DENY）
        self.tool_overrides: Dict[str, GovernanceDecision] = dict(tool_overrides or {})

        # 命令白名单：命中即免检放行（优先级低于 tool_overrides）
        self._whitelist_lock = threading.RLock()
        self._whitelist_path = Path(whitelist_path) if whitelist_path else None
        if whitelist_entries is not None:
            self._whitelist = [dict(e) for e in whitelist_entries]
        else:
            self._whitelist = []
            self._load_whitelist()

    def evaluate(
        self,
        command: str,
        tool_name: str = "shell",
        user_id: Optional[str] = None,
        file_paths: Optional[str] = None,
    ) -> GovernanceResult:
        """对一次工具/命令调用做策略裁决。

        优先级: tool_overrides > 白名单 > 内容检测。
        """
        # 工具级覆盖优先于内容检测结果（显式配置 > 自动推断）
        if tool_name in self.tool_overrides:
            override = self.tool_overrides[tool_name]
            return GovernanceResult(
                decision=override,
                reasons=[f"工具 '{tool_name}' 命中策略覆盖: {override.value}"],
            )

        # 白名单免检放行
        hit = self.match_whitelist(command, tool_name)
        if hit is not None:
            return GovernanceResult(
                decision=GovernanceDecision.ALLOW,
                reasons=[f"命中白名单条目 {hit.get('id', '?')}: {hit.get('pattern', '')}"],
            )

        tool_params: Dict[str, Any] = {"command": command}
        if file_paths is not None:
            tool_params["path"] = file_paths

        guard_result = self.engine.guard(tool_name, tool_params)
        findings = list(getattr(guard_result, "findings", []) or [])
        if not isinstance(findings, list):
            findings = []

        critical = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.CRITICAL]
        high = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.HIGH]
        medium = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.MEDIUM]

        # 注意：不使用 guard_result.safe 做裁决 —— 该标志在 AUTO 模式下
        # 对任何 >=HIGH 的发现都为 False，会让 SANDBOX 分支变成死代码。
        if critical:
            reasons = [f"拦截: {getattr(f, 'message', str(f))}" for f in critical]
            return GovernanceResult(
                decision=GovernanceDecision.DENY,
                reasons=reasons or ["命中阻断级规则"],
                findings=findings,
            )

        if high:
            if self.ask_on_high:
                return GovernanceResult(
                    decision=GovernanceDecision.ASK,
                    reasons=[f"需确认: {getattr(f, 'message', str(f))}" for f in high],
                    findings=findings,
                )
            return GovernanceResult(
                decision=GovernanceDecision.SANDBOX,
                reasons=[f"高风险,启用沙箱: {getattr(f, 'message', str(f))}" for f in high],
                severity=self.sandbox_severity,
                findings=findings,
            )

        if medium and self.ask_on_high:
            return GovernanceResult(
                decision=GovernanceDecision.ASK,
                reasons=[f"中风险,建议确认: {getattr(f, 'message', str(f))}" for f in medium],
                findings=findings,
            )

        return GovernanceResult(decision=self.default_action, reasons=[], findings=findings)

    def execute_if_allowed(
        self,
        command: str,
        timeout: float = 30.0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        tool_name: str = "shell",
        user_id: Optional[str] = None,
        file_paths: Optional[str] = None,
    ) -> Dict[str, Any]:
        """裁决后执行：DENY 直接拦截，SANDBOX 走隔离沙箱，其余常规执行。"""
        result = self.evaluate(command, tool_name=tool_name, user_id=user_id, file_paths=file_paths)
        if result.decision == GovernanceDecision.DENY:
            logger.warning("Governance DENY: %s", "; ".join(result.reasons))
            return {
                "success": False,
                "output": "",
                "error": "被治理策略拦截: " + "; ".join(result.reasons),
                "return_code": -1,
                "governance": result.to_dict(),
            }
        if result.decision == GovernanceDecision.SANDBOX:
            logger.info("Governance SANDBOX (%s)", result.severity.value)
            return execute_in_sandbox(
                command, timeout=timeout, cwd=cwd, env=env, severity=result.severity
            )
        # ASK / ALLOW：当前实现视为允许（交互确认交由上层 UI）
        return execute_in_sandbox(command, timeout=timeout, cwd=cwd, env=env, severity=SandboxSeverity.NONE)

    # ── 命令白名单 ──────────────────────────────────────────────

    def match_whitelist(self, command: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """返回第一条命中的白名单条目；无命中返回 None。"""
        with self._whitelist_lock:
            entries = list(self._whitelist)
        for entry in entries:
            scoped_tool = entry.get("tool")
            if scoped_tool and scoped_tool != tool_name:
                continue
            pattern = str(entry.get("pattern", ""))
            match_type = entry.get("match_type", "prefix")
            try:
                if match_type == "exact":
                    matched = command.strip() == pattern.strip()
                elif match_type == "regex":
                    matched = re.search(pattern, command) is not None
                else:  # 默认 prefix
                    matched = command.startswith(pattern)
            except re.error:
                logger.warning("白名单正则无效，忽略该条目: %s", pattern)
                continue
            if matched:
                return entry
        return None

    def list_whitelist_entries(self) -> List[Dict[str, Any]]:
        with self._whitelist_lock:
            return [dict(e) for e in self._whitelist]

    def add_whitelist_entry(
        self,
        pattern: str,
        match_type: str = "prefix",
        tool: Optional[str] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        entry = {
            "id": f"wl-{uuid.uuid4().hex[:10]}",
            "pattern": pattern,
            "match_type": match_type if match_type in ("exact", "regex", "prefix") else "prefix",
            "tool": tool,
            "note": note,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._whitelist_lock:
            self._whitelist.append(entry)
            self._save_whitelist()
        logger.info("白名单新增条目 %s: %s (%s)", entry["id"], pattern, match_type)
        return dict(entry)

    def remove_whitelist_entry(self, entry_id: str) -> bool:
        with self._whitelist_lock:
            before = len(self._whitelist)
            self._whitelist = [e for e in self._whitelist if e.get("id") != entry_id]
            removed = len(self._whitelist) < before
            if removed:
                self._save_whitelist()
        return removed

    def _load_whitelist(self) -> None:
        if self._whitelist_path is None or not self._whitelist_path.exists():
            return
        try:
            data = json.loads(self._whitelist_path.read_text(encoding="utf-8"))
            entries = data.get("entries", []) if isinstance(data, dict) else []
            self._whitelist = [e for e in entries if isinstance(e, dict)]
        except Exception as e:  # noqa: BLE001 - 配置损坏时降级为空白名单
            logger.warning("白名单文件加载失败（按空白名单处理）: %s", e)
            self._whitelist = []

    def _save_whitelist(self) -> None:
        if self._whitelist_path is None:
            return
        try:
            self._whitelist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "entries": self._whitelist,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._whitelist_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001 - 写失败不影响内存态
            logger.error("白名单保存失败: %s", e)


_governance_instance: Optional[GovernancePolicy] = None


def _default_whitelist_path() -> Path:
    return Path.home() / ".neurova" / "config" / "governance_whitelist.json"


def get_governance() -> GovernancePolicy:
    global _governance_instance
    if _governance_instance is None:
        # 产品语义: 高风险操作默认询问用户（弹窗确认），而非静默沙箱。
        # 库级默认（ask_on_high=False）保持沙箱语义，供测试/嵌入场景使用。
        _governance_instance = GovernancePolicy(
            whitelist_path=_default_whitelist_path(),
            ask_on_high=True,
        )
    return _governance_instance


def reset_governance() -> None:
    global _governance_instance
    _governance_instance = None


__all__ = [
    "GovernanceDecision",
    "GovernanceResult",
    "GovernancePolicy",
    "get_governance",
    "reset_governance",
]
