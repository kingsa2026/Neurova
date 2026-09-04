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

# P1-7：平台真隔离后端探测表（bwrap/seatbelt/docker；Windows AppContainer 未实现不入列）
_ENFORCED_SANDBOX_BACKENDS = {}


def is_policy_denial(result: Any) -> bool:
    """判定执行结果是否为"策略性拒绝"（治理拦截/待审批）。

    单源判定（闭环审计断点 B）：治理 DENY/SANDBOX 阻止/ASK 待确认产生的
    结果 dict 携带 governance / pending_approval 键——这是"决策"而非
    "后端故障"。消费方（on_tool_executed 三处统计、熔断器观察者）必须
    使用本函数区分，避免策略事件被误记为工具失败。
    """
    if not isinstance(result, dict):
        return False
    # param_guard 键：工具参数守卫的拒绝（截断 JSON 无法配平等）同样是
    # "决策"——OpenOcta 启发 P1-5，与治理 DENY 同源口径，不计工具故障。
    # swarm_rejection 键：蜂群 spawn 数据层结构化拒绝（OpenOcta 启发 P2-10
    # 三明治，硬限阀门）同为"决策"非"后端故障"。
    return bool(
        result.get("governance")
        or result.get("pending_approval")
        or result.get("param_guard")
        or result.get("swarm_rejection")
    )


def _platform_has_enforced_sandbox() -> bool:
    """当前平台是否存在任一可用真隔离后端（诚实化：占位后端不算数）。"""
    for name, backend in _ENFORCED_SANDBOX_BACKENDS.items():
        try:
            if backend.available():
                return True
        except Exception:
            continue
    return False


def _tool_sandbox_enforce_enabled() -> bool:
    """P2-15 声明面强制路由开关（默认关）。

    NEUROVA_TOOL_SANDBOX_ENFORCE 精确等于 "1" 才开启——避免 "false"/"0"
    之外任意真值字符串意外开启的经典坑。开启后，builtin_tools 声明了
    sandbox_required 的工具，其调用被强制路由进沙箱裁决链。
    """
    import os

    return os.environ.get("NEUROVA_TOOL_SANDBOX_ENFORCE") == "1"


def check_outbound_url(url: str, *, allow_private: bool = False) -> bool:
    """全局出网校验层（P1-7：url_guard P0-1 产物统一暴露）。

    治理/工具层出网前统一经此校验；私网/保留段拒绝（SSRF 防护）。
    Raises:
        ValueError: URL 被拒
    """
    from neurova.security.url_guard import assert_public_url

    assert_public_url(url, allow_private=allow_private)
    return True

logger = get_logger(__name__)


class GovernanceDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    SANDBOX = "sandbox"


# P0-6 分段审批适用面：shell 方言工具。run_code 的 code 是 Python/脚本
# 本体（|、;、&& 是代码语法而非 shell 连接符），分段会造成合法代码误入
# 审批——非 shell 工具保持整串白名单/内容检测旧行为。
_SEGMENTED_SHELL_TOOLS = frozenset({
    "shell",
    "computer_shell",
    "execute_cli_tool",
    "process",
    "terminal",
    "bash",
})


@dataclass
class GovernanceResult:
    decision: GovernanceDecision
    reasons: List[str] = field(default_factory=list)
    severity: SandboxSeverity = SandboxSeverity.NONE
    findings: List[Any] = field(default_factory=list)
    # P0-6 分段审批：多段命令的候选段列表（CommandSegment.to_dict）。
    # 单段命令恒 None（等价旧行为）；审批卡据此逐段展示。
    segments: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "severity": self.severity.value,
            "finding_count": len(self.findings),
        }
        if self.segments:
            d["segments"] = list(self.segments)
        return d


# 参数提取的约定键名（非 scan_all 模式保持既有语义）
_ADJUDICABLE_COMMAND_KEYS = ("command", "code")
_ADJUDICABLE_PATH_KEYS = ("file_path", "path")
# 路径型参数启发式：绝对路径（POSIX/Windows 盘符/UNC），供敏感路径规则用
_PATH_LIKE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~[\\/])")


def extract_adjudicable_params(params: Any, scan_all: bool = False) -> tuple:
    """从工具参数中提取可裁决内容 (command 文本, file_paths)。

    scan_all=True（MCP 等动态来源）：全部参数整体序列化进 command，
    不依赖约定键名——否则动态工具换个参数名即可绕过预检（P0-2 / M4）。
    scan_all=False：保持既有四键名提取语义。
    """
    if not isinstance(params, dict) or not params:
        return "", None

    if scan_all:
        try:
            command = json.dumps(params, ensure_ascii=False, default=str)
        except Exception:
            command = str(params)
        file_paths = next(
            (
                v
                for v in params.values()
                if isinstance(v, str) and _PATH_LIKE.match(v)
            ),
            None,
        )
        return command, file_paths

    command = next(
        (
            params[k]
            for k in _ADJUDICABLE_COMMAND_KEYS
            if isinstance(params.get(k), str) and params[k].strip()
        ),
        "",
    )
    file_paths = next(
        (
            params[k]
            for k in _ADJUDICABLE_PATH_KEYS
            if isinstance(params.get(k), str) and params[k]
        ),
        None,
    )
    return command, file_paths


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

        # P0-6 分段审批（OpenClaw 启发）：多段命令全部段命中白名单才放行；
        # 任一段未命中 → 不再享受白名单免检，整条命令回落内容检测。
        # 内容检测（critical/high DENY/SANDBOX）恒先于分段 ASK——内容级
        # 危险信号不得被"白名单未命中→ASK"弱化；分段 ASK 只在内容检测
        # 无发现时兜底（防"白名单段+无害注入段"借 default_action 放行）。
        # 单段命令走 match_whitelist 原语义（字节等价旧行为）。
        from neurova.security.command_segments import parse_command_segments

        segs = (
            parse_command_segments(command)
            if command and (tool_name in _SEGMENTED_SHELL_TOOLS or tool_name.startswith("mcp."))
            else []
        )
        is_multi_seg = len(segs) > 1
        if is_multi_seg:
            seg_hits = [self.match_whitelist(s.text, tool_name) for s in segs]
            if all(h is not None for h in seg_hits):
                return GovernanceResult(
                    decision=GovernanceDecision.ALLOW,
                    reasons=[f"分段审批: 全部 {len(segs)} 段命中白名单"],
                    segments=[s.to_dict() for s in segs],
                )
            hit = None
        else:
            hit = self.match_whitelist(command, tool_name)

        if hit is not None:
            return GovernanceResult(
                decision=GovernanceDecision.ALLOW,
                reasons=[f"命中白名单条目 {hit.get('id', '?')}: {hit.get('pattern', '')}"],
            )

        tool_params: Dict[str, Any] = {"command": command}
        if file_paths is not None:
            tool_params["path"] = file_paths

        # P0-6：多段命令的分段信息透传到裁决结果（审批卡逐段展示）
        _seg_dicts_if_multi = [s.to_dict() for s in segs] if len(segs) > 1 else None

        guard_result = self.engine.guard(tool_name, tool_params)
        findings = list(getattr(guard_result, "findings", []) or [])
        if not isinstance(findings, list):
            findings = []

        critical = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.CRITICAL]
        high = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.HIGH]
        medium = [f for f in findings if getattr(f, "severity", None) == GuardSeverity.MEDIUM]        # 注意：不使用 guard_result.safe 做裁决 —— 该标志在 AUTO 模式下
        # 对任何 >=HIGH 的发现都为 False，会让 SANDBOX 分支变成死代码。
        if critical:
            reasons = [f"拦截: {getattr(f, 'message', str(f))}" for f in critical]
            return GovernanceResult(
                decision=GovernanceDecision.DENY,
                reasons=reasons or ["命中阻断级规则"],
                findings=findings,
                segments=_seg_dicts_if_multi,
            )

        if high:
            if self.ask_on_high:
                return GovernanceResult(
                    decision=GovernanceDecision.ASK,
                    reasons=[f"需确认: {getattr(f, 'message', str(f))}" for f in high],
                    findings=findings,
                    segments=_seg_dicts_if_multi,
                )
            # P1-7 诚实化：平台上无真隔离后端时，SANDBOX 判定是谎言（实际裸跑），
            # 升级为 DENY——拒绝优于静默放行
            if not _platform_has_enforced_sandbox():
                return GovernanceResult(
                    decision=GovernanceDecision.DENY,
                    reasons=[f"高风险且当前平台无可用沙箱隔离，拒绝执行: "
                             + "; ".join(getattr(f, "message", str(f)) for f in high)],
                    severity=SandboxSeverity.NONE,
                    findings=findings,
                    segments=_seg_dicts_if_multi,
                )
            return GovernanceResult(
                decision=GovernanceDecision.SANDBOX,
                reasons=[f"高风险,启用沙箱: {getattr(f, 'message', str(f))}" for f in high],
                severity=self.sandbox_severity,
                findings=findings,
                segments=_seg_dicts_if_multi,
            )

        if medium and self.ask_on_high:
            return GovernanceResult(
                decision=GovernanceDecision.ASK,
                reasons=[f"中风险,建议确认: {getattr(f, 'message', str(f))}" for f in medium],
                findings=findings,
                segments=_seg_dicts_if_multi,
            )

        # P0-6 分段 ASK 兜底（顺序在内容检测之后）：多段命令有段未命中
        # 白名单且内容检测无发现 → 逐段确认而非 default_action 放行。
        # 注入段借白名单段搭便车的最后一道闸。
        if is_multi_seg and any(h is None for h in seg_hits):
            offender = next(s for s, h in zip(segs, seg_hits) if h is None)
            return GovernanceResult(
                decision=GovernanceDecision.ASK,
                reasons=[
                    f"分段审批: 段 '{offender.text[:80]}' 未命中白名单，链式命令需逐段确认"
                ],
                findings=findings,
                segments=_seg_dicts_if_multi,
            )

        return GovernanceResult(
            decision=self.default_action, reasons=[], findings=findings, segments=_seg_dicts_if_multi
        )

    def evaluate_tool_call(
        self,
        tool_name: str,
        params: Any,
        user_id: Optional[str] = None,
        scan_all: bool = False,
    ) -> Optional[GovernanceResult]:
        """工具调用治理评估入口（P0-2 / 评测 M4）。

        scan_all=True（MCP 等动态来源工具，mcp.* 命名空间）时对全部参数
        整体序列化扫描——否则动态工具把参数换个键名（不叫 command/path）
        即可绕过预检。scan_all=False 保持既有四键名提取语义。

        Returns:
            GovernanceResult: 命中可裁决内容时的裁决
            None: 无可裁决内容（不触发覆盖/白名单/内容检测）
        """
        # 单调守卫（可插拔拒绝链，语义见 monotonic_guard 模块头注释）：
        # 任一守卫 DENY 即拒绝，先于内容裁决；守卫契约上不存在 ALLOW，
        # 空注册表恒为 None —— 与接入前行为完全等价。
        from neurova.security.monotonic_guard import get_monotonic_guards

        guard_outcome = get_monotonic_guards().check_all(tool_name, params, user_id)
        if guard_outcome is not None:
            return GovernanceResult(
                decision=GovernanceDecision.DENY,
                reasons=[guard_outcome.message],
                severity=SandboxSeverity.NONE,
                findings=[guard_outcome.to_dict()],
            )

        # P2-15 声明面强制路由（默认关）：声明 sandbox_required 的工具
        # 在开关开启时无条件进入沙箱/Deny 语义，先于白名单与内容检测
        # ——声明是开发者对工具安全底线的结构化承诺，不因运行时白名单
        # 或"参数恰好无害"而失效。开关关闭时此层恒 None（逐字节等价旧路径）。
        declaration_verdict = self._sandbox_declaration_verdict(tool_name)
        if declaration_verdict is not None:
            return declaration_verdict

        command, file_paths = extract_adjudicable_params(params, scan_all=scan_all)
        if not command and file_paths is None:
            return None
        return self.evaluate(
            command=command, tool_name=tool_name, user_id=user_id, file_paths=file_paths
        )

    def _sandbox_declaration_verdict(self, tool_name: str) -> Optional["GovernanceResult"]:
        """P2-15：builtin 工具 sandboxRequired 声明位的强制裁决。

        - 开关关闭（默认）→ None，调用方行为与接入前完全一致
        - mcp.* 声明工具：无命令行沙箱语义（与 _governance_precheck 的
          MCP-SANDBOX 阻断同口径）→ 直接 DENY
        - 非 MCP 声明工具：有真隔离后端 → SANDBOX（复用既有沙箱执行链）；
          无后端 → DENY（P1-7 诚实化：拒绝优于裸跑）
        """
        if not _tool_sandbox_enforce_enabled():
            return None
        try:
            from neurova.builtin_tools import get_builtin_tool_sandbox_declaration

            if get_builtin_tool_sandbox_declaration(tool_name) is not True:
                return None
        except Exception:  # noqa: BLE001 - 声明表不可达时不改变裁决路径
            return None

        if tool_name.startswith("mcp."):
            return GovernanceResult(
                decision=GovernanceDecision.DENY,
                reasons=[
                    f"工具 '{tool_name}' 声明 sandboxRequired，MCP 调用无命令行沙箱语义，已阻止"
                ],
                severity=SandboxSeverity.NONE,
            )
        if _platform_has_enforced_sandbox():
            return GovernanceResult(
                decision=GovernanceDecision.SANDBOX,
                reasons=[f"工具 '{tool_name}' 声明 sandboxRequired，强制沙箱执行"],
                severity=self.sandbox_severity,
            )
        return GovernanceResult(
            decision=GovernanceDecision.DENY,
            reasons=[
                f"工具 '{tool_name}' 声明 sandboxRequired，但当前平台无强制沙箱后端，拒绝执行"
            ],
            severity=SandboxSeverity.NONE,
        )

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
    "is_policy_denial",
    "reset_governance",
]
