"""
Neurova 工具守卫 (Tool Guard) 2.0

在 Agent 调用工具前实时检测危险模式，防止恶意操作。
结合 Neurova 的认知增强特性。
"""

from __future__ import annotations

import datetime
import os
from neurova.core.logger import get_logger
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Set

logger = get_logger(__name__)


class GuardSeverity(str, Enum):
    """威胁严重程度"""

    CRITICAL = "critical"  # 必须阻止
    HIGH = "high"  # 高风险
    MEDIUM = "medium"  # 中等风险
    LOW = "low"  # 低风险
    INFO = "info"  # 信息性


class GuardThreatCategory(str, Enum):
    """威胁类别"""

    COMMAND_INJECTION = "command_injection"  # 命令注入
    PATH_TRAVERSAL = "path_traversal"  # 路径遍历
    SHELL_EVASION = "shell_evasion"  # Shell 逃逸
    FILE_DESTRUCTION = "file_destruction"  # 文件破坏
    NETWORK_EXFILTRATION = "network_exfiltration"  # 网络外泄
    PRIVILEGE_ESCALATION = "privilege_escalation"  # 权限提升
    DATA_LEAKAGE = "data_leakage"  # 数据泄漏
    REMOTE_CONTROL = "remote_control"  # 远程控制（反弹 shell 等）
    DESTRUCTIVE_COMMAND = "destructive_command"  # 毁灭性命令（rm -rf / 等）


@dataclass
class GuardFinding:
    """守卫发现"""

    rule_id: str = ""
    severity: GuardSeverity = GuardSeverity.INFO
    category: GuardThreatCategory = GuardThreatCategory.COMMAND_INJECTION
    message: str = ""
    evidence: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
        }
        if self.evidence:
            result["evidence"] = self.evidence
        if self.suggestion:
            result["suggestion"] = self.suggestion
        return result


@dataclass
class ToolGuardResult:
    """工具守卫结果"""

    tool_name: str = ""
    safe: bool = True
    findings: List[GuardFinding] = field(default_factory=list)
    checked_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_block(self) -> bool:
        """是否应该阻止执行"""
        return not self.safe

    def to_dict(self) -> Dict[str, Any]:
        severity_counts: Dict[str, int] = {}
        for f in self.findings:
            key = f"{f.severity.value}_count"
            severity_counts[key] = severity_counts.get(key, 0) + 1

        return {
            "tool_name": self.tool_name,
            "safe": self.safe,
            "findings": [f.to_dict() for f in self.findings],
            "checked_at": self.checked_at.isoformat(),
            "finding_count": len(self.findings),
            "should_block": self.should_block,
            **severity_counts,
        }


@dataclass
class ToolGuardRule:
    """工具守卫规则"""

    rule_id: str = ""
    name: str = ""
    pattern: str = ""
    severity: GuardSeverity = GuardSeverity.MEDIUM
    category: GuardThreatCategory = GuardThreatCategory.COMMAND_INJECTION
    message: str = ""
    description: str = ""
    enabled: bool = True
    suggestion: Optional[str] = None
    _compiled: Optional[Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        if self.pattern:
            try:
                self._compiled = re.compile(self.pattern, re.IGNORECASE)
            except re.error:
                self._compiled = None

    def matches(self, text: str) -> bool:
        if not self._compiled or not self.enabled:
            return False
        return self._compiled.search(text) is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "pattern": self.pattern,
            "severity": self.severity.value,
            "category": self.category.value,
            "message": self.message,
            "enabled": self.enabled,
        }


class BaseGuardian:
    """守护者基类"""

    @property
    def name(self) -> str:
        raise NotImplementedError

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        raise NotImplementedError


class RuleBasedToolGuardian(BaseGuardian):
    """基于规则的工具守护者"""

    def __init__(self):
        self.rules: Dict[str, ToolGuardRule] = {}
        self._load_default_rules()

    @property
    def name(self) -> str:
        return "rule_based"

    def _load_default_rules(self):
        """加载默认规则"""
        default_rules = [
            ToolGuardRule(
                rule_id="rm_rf",
                name="rm -rf",
                pattern=r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--recursive)\b",
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.FILE_DESTRUCTION,
                message="检测到 rm -rf 危险命令",
                suggestion="请使用更安全的文件删除方式",
            ),
            ToolGuardRule(
                rule_id="rm_root",
                name="删除根目录",
                pattern=r"\brm\s+.*\s+/\s*$",
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.FILE_DESTRUCTION,
                message="检测到尝试删除根目录",
            ),
            ToolGuardRule(
                rule_id="chmod_777",
                name="chmod 777",
                pattern=r"\bchmod\s+777\b",
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.PRIVILEGE_ESCALATION,
                message="检测到 chmod 777 权限设置",
                suggestion="使用更严格的权限设置",
            ),
            ToolGuardRule(
                rule_id="curl_pipe",
                name="curl | sh",
                pattern=r"(curl|wget)\s+.*\|\s*(sh|bash|zsh)",
                # HIGH（而非 CRITICAL）：远程脚本执行可沙箱隔离，
                # 由 GovernancePolicy 路由到 SANDBOX；彻底阻断会破坏合法安装流程
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.NETWORK_EXFILTRATION,
                message="检测到远程脚本执行（curl | sh）",
            ),
            ToolGuardRule(
                rule_id="eval_command",
                name="eval 命令",
                pattern=r"\beval\s+",
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.COMMAND_INJECTION,
                message="检测到 eval 命令执行",
            ),
            ToolGuardRule(
                rule_id="fork_bomb",
                name="Fork 炸弹",
                pattern=r":\(\)\s*\{\s*:\|:&\s*\};:",
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.FILE_DESTRUCTION,
                message="检测到 Fork 炸弹",
            ),
            ToolGuardRule(
                rule_id="mkfs_disk",
                name="格式化磁盘",
                pattern=r"\bmkfs\b",
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.FILE_DESTRUCTION,
                message="检测到磁盘格式化命令",
            ),
            ToolGuardRule(
                rule_id="dd_disk",
                name="dd 磁盘操作",
                pattern=r"\bdd\s+.*of=/dev/[sh]d",
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.FILE_DESTRUCTION,
                message="检测到 dd 磁盘写入操作",
            ),
            ToolGuardRule(
                rule_id="nc_listener",
                name="netcat 监听",
                pattern=r"\bnc\s+.*-l",
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.NETWORK_EXFILTRATION,
                message="检测到 netcat 监听模式",
            ),
            ToolGuardRule(
                rule_id="iptables_flush",
                name="iptables 清空",
                pattern=r"\biptables\s+-F\b",
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.PRIVILEGE_ESCALATION,
                message="检测到 iptables 规则清空",
            ),
            ToolGuardRule(
                rule_id="history_clear",
                name="清除历史",
                pattern=r"\b(history\s+-c|rm\s+.*\.bash_history)\b",
                severity=GuardSeverity.MEDIUM,
                category=GuardThreatCategory.DATA_LEAKAGE,
                message="检测到清除命令历史操作",
            ),
        ]

        for rule in default_rules:
            self.rules[rule.rule_id] = rule

    def add_rule(self, rule: ToolGuardRule):
        """添加规则"""
        self.rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """移除规则"""
        if rule_id in self.rules:
            del self.rules[rule_id]
            return True
        return False

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        """检查工具输入"""
        findings: List[GuardFinding] = []

        for rule in self.rules.values():
            if not rule.enabled:
                continue

            if rule.matches(tool_input):
                finding = GuardFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    category=rule.category,
                    message=rule.message,
                    evidence=tool_input[:200],
                    suggestion=rule.suggestion,
                )
                findings.append(finding)

        return findings


class ShellEvasionGuardian(BaseGuardian):
    """Shell 逃逸检测守护者"""

    def __init__(self):
        self._evasion_patterns = self._compile_evasion_patterns()

    @property
    def name(self) -> str:
        return "shell_evasion"

    def _compile_evasion_patterns(self) -> List[Pattern]:
        """编译逃逸检测模式"""
        # (正则, 严重度, 威胁类别, 描述)；CRITICAL = 毁灭性/远控，DENY
        patterns = [
            # ── CRITICAL: 反弹 shell / 远程控制 ──────────────────
            (r"/dev/tcp/[^\s'\"]+", GuardSeverity.CRITICAL, GuardThreatCategory.REMOTE_CONTROL,
             "反弹 shell (/dev/tcp)"),
            (r"\bnc(?:at)?\s+(-e\s|-c\s|\-\-exec\b|\-\-sh-exec\b)", GuardSeverity.CRITICAL,
             GuardThreatCategory.REMOTE_CONTROL, "nc 反弹 shell (-e/-c)"),
            (r"\bsocat\s+.*EXEC:", GuardSeverity.CRITICAL, GuardThreatCategory.REMOTE_CONTROL,
             "socat 反弹 shell (EXEC)"),
            (r"\bbash\s+-i\s+>&", GuardSeverity.CRITICAL, GuardThreatCategory.REMOTE_CONTROL,
             "交互式反弹 shell"),
            # ── CRITICAL: 毁灭性命令 ────────────────────────────
            (r"\brm\s+(-\w+\s+)*-\w*(rf|fr)\w*\s+/(?:\s|$)", GuardSeverity.CRITICAL,
             GuardThreatCategory.DESTRUCTIVE_COMMAND, "递归删除根目录"),
            (r"\brm\s+(-\w+\s+)*-\w*(rf|fr)\w*\s+[cC]:[\\/]+(?:windows|users|program)",
             GuardSeverity.CRITICAL, GuardThreatCategory.DESTRUCTIVE_COMMAND,
             "递归删除 Windows 系统/用户目录"),
            (r"\bmkfs(?:\.\w+)?\b", GuardSeverity.CRITICAL, GuardThreatCategory.DESTRUCTIVE_COMMAND,
             "格式化文件系统"),
            (r"\bdd\s+if=/dev/(?:zero|random|urandom)\s+of=/dev/", GuardSeverity.CRITICAL,
             GuardThreatCategory.DESTRUCTIVE_COMMAND, "dd 覆写磁盘"),
            (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:", GuardSeverity.CRITICAL,
             GuardThreatCategory.DESTRUCTIVE_COMMAND, "fork 炸弹"),
            (r"\bchmod\s+(-R\s+)?777\s+/(?:\s|$)", GuardSeverity.CRITICAL,
             GuardThreatCategory.DESTRUCTIVE_COMMAND, "全盘开放权限"),
            # ── HIGH: Shell 逃逸技术 ────────────────────────────
            (r"\$\([^)]*\)", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "命令替换 $()"),
            (r"`[^`]+`", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "反引号命令替换"),
            (r"base64\s+(-d|--decode)", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "Base64 解码"),
            (r"\\x[0-9a-fA-F]{2}", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "十六进制编码"),
            (r"\|\s*(python[23]?|perl|ruby|node|php)\b", GuardSeverity.HIGH,
             GuardThreatCategory.SHELL_EVASION, "管道到脚本解释器"),
            # curl | sh / wget | bash：远程脚本直接执行（方案 P0-1.2 明确要求）
            (r"\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", GuardSeverity.HIGH,
             GuardThreatCategory.SHELL_EVASION, "管道到 shell 执行"),
            (r"\|\s*(ba|z|k)?sh\s*$", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "管道到 shell 执行"),
            (r"\\x00", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "Null 字节注入"),
            (r"\$\{[^}]*\}", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "环境变量展开"),
            (r"<\([^)]*\)", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "进程替换"),
        ]
        return [
            (re.compile(p, re.IGNORECASE), severity, cat, desc)
            for p, severity, cat, desc in patterns
        ]

    def _has_command_substitution(self, text: str) -> bool:
        """检查命令替换"""
        patterns = [
            re.compile(r"\$\([^)]*\)"),
            re.compile(r"`[^`]+`"),
            re.compile(r"<\([^)]*\)"),
        ]
        return any(p.search(text) for p in patterns)

    def _has_encoding_evasion(self, text: str) -> bool:
        """检查编码逃逸"""
        patterns = [
            re.compile(r"base64\s+(-d|--decode)", re.IGNORECASE),
            re.compile(r"\\x[0-9a-fA-F]{2}", re.IGNORECASE),
            re.compile(r"\\u[0-9a-fA-F]{4}", re.IGNORECASE),
        ]
        return any(p.search(text) for p in patterns)

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        """检测 Shell 逃逸"""
        findings: List[GuardFinding] = []

        for pattern, severity, category, desc in self._evasion_patterns:
            match = pattern.search(tool_input)
            if match:
                finding = GuardFinding(
                    rule_id=f"shell_{desc.replace(' ', '_').lower()}",
                    severity=severity,
                    category=category,
                    message=f"检测到高危模式: {desc}",
                    evidence=match.group(),
                    suggestion="该命令被治理策略拦截或要求沙箱执行",
                )
                findings.append(finding)

        return findings


class FilePathGuardian(BaseGuardian):
    """文件路径守护者"""

    # 方案 P0-1.3: 用户敏感目录（按目录名匹配，跨平台）
    _USER_SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker"}
    # 方案 P0-1.3: 敏感凭据文件（按文件名/后缀匹配）
    _SENSITIVE_FILES = {".env", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa",
                        "credentials", "credentials.json"}

    def __init__(self):
        self._protected_paths = {
            "/etc/passwd",
            "/etc/shadow",
            "/etc/sudoers",
            "/etc/ssh",
            "/root",
            "/boot",
            "/proc/self/environ",
            "/proc/self/mem",
        }
        self._safe_paths = {"/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"}
        # Windows 系统目录（大小写不敏感前缀匹配）
        self._windows_protected_prefixes = ("c:\\windows", "c:\\program files")

    @property
    def name(self) -> str:
        return "file_path"

    def _is_likely_path_param(self, value: str) -> bool:
        """判断是否是路径参数"""
        return "/" in value or "\\" in value or ".." in value

    def _match_sensitive_component(self, path: str) -> Optional[str]:
        """检查路径中是否包含用户敏感目录或凭据文件，返回命中描述。"""
        parts = re.split(r"[\\/]+", path.lower())
        if not parts:
            return None
        for i, part in enumerate(parts[:-1]):
            if part in self._USER_SENSITIVE_DIRS:
                return f"用户敏感目录 ~/{part}"
        basename = parts[-1]
        for stem in (basename, os.path.splitext(basename)[0]):
            if stem in self._SENSITIVE_FILES:
                return f"敏感凭据文件 {stem}"
        return None

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        """检查文件路径安全性"""
        findings: List[GuardFinding] = []

        # 从 context 中提取路径
        path = context.get("path", "")
        if not path:
            # 尝试从工具输入中提取路径
            path_match = re.search(r"(?:path|file|dir)=([^\s]+)", tool_input)
            if path_match:
                path = path_match.group(1)

        if not path:
            return findings

        # 检查路径遍历
        if ".." in path:
            findings.append(
                GuardFinding(
                    rule_id="path_traversal",
                    severity=GuardSeverity.HIGH,
                    category=GuardThreatCategory.PATH_TRAVERSAL,
                    message=f"检测到路径遍历: {path}",
                    evidence=path,
                    suggestion="使用绝对路径或验证路径合法性",
                )
            )

        # 检查系统保护路径（兼容 ~ 展开形式与原始形式）
        expanded = os.path.expanduser(path)
        candidates = {path, expanded}
        hit_protected: Optional[str] = None
        for candidate in candidates:
            norm = candidate.replace("\\", "/")
            if norm in self._safe_paths:
                continue
            for protected in self._protected_paths:
                if norm.startswith(protected) or candidate.startswith(protected):
                    hit_protected = protected
                    break
            if hit_protected:
                break
        if hit_protected:
            findings.append(
                GuardFinding(
                    rule_id="protected_path",
                    severity=GuardSeverity.HIGH,
                    category=GuardThreatCategory.PATH_TRAVERSAL,
                    message=f"访问受保护路径: {hit_protected}",
                    evidence=path,
                    suggestion=f"路径 {hit_protected} 受系统保护",
                )
            )

        # 检查 Windows 系统目录（大小写不敏感）
        lowered = path.lower()
        if any(lowered.startswith(p) for p in self._windows_protected_prefixes):
            findings.append(
                GuardFinding(
                    rule_id="windows_system_path",
                    severity=GuardSeverity.HIGH,
                    category=GuardThreatCategory.PATH_TRAVERSAL,
                    message=f"访问 Windows 系统目录: {path}",
                    evidence=path,
                    suggestion="Windows 系统目录受保护，禁止工具直接读写",
                )
            )

        # 方案 P0-1.3: 用户敏感目录 / 凭据文件（~/.ssh、~/.aws、.env 等）
        sensitive_hit = self._match_sensitive_component(path)
        if sensitive_hit:
            findings.append(
                GuardFinding(
                    rule_id="sensitive_user_path",
                    severity=GuardSeverity.HIGH,
                    category=GuardThreatCategory.DATA_LEAKAGE,
                    message=f"访问用户敏感位置: {sensitive_hit}",
                    evidence=path,
                    suggestion="凭据类文件禁止通过 Agent 工具读写",
                )
            )

        # 检查通配符
        if "*" in path or "?" in path:
            findings.append(
                GuardFinding(
                    rule_id="wildcard_path",
                    severity=GuardSeverity.MEDIUM,
                    category=GuardThreatCategory.PATH_TRAVERSAL,
                    message=f"检测到路径通配符: {path}",
                    evidence=path,
                    suggestion="避免在路径中使用通配符",
                )
            )

        return findings


class ApprovalMode(str, Enum):
    """审批模式"""

    AUTO = "auto"  # 自动审批（安全通过，危险阻止）
    MANUAL = "manual"  # 手动审批（所有操作等待人工）
    STRICT = "strict"  # 严格模式（低风险也阻止）


class ToolGuardEngine:
    """工具守卫引擎"""

    def __init__(self, approval_mode: ApprovalMode = ApprovalMode.AUTO):
        self.enabled: bool = True
        self.approval_mode: ApprovalMode = approval_mode
        self.guardians: List[BaseGuardian] = []
        self._denied_tools: Set[str] = set()

        # 加载默认守护者
        self._default_guardians()

    def _default_guardians(self):
        """加载默认守护者"""
        self.guardians.append(RuleBasedToolGuardian())
        self.guardians.append(ShellEvasionGuardian())
        self.guardians.append(FilePathGuardian())

    def add_guardian(self, guardian: BaseGuardian):
        """添加守护者"""
        if guardian not in self.guardians:
            self.guardians.append(guardian)

    def remove_guardian(self, guardian: BaseGuardian) -> bool:
        """移除守护者"""
        if guardian in self.guardians:
            self.guardians.remove(guardian)
            return True
        return False

    def add_denied_tool(self, tool_name: str):
        """添加拒绝工具"""
        self._denied_tools.add(tool_name)

    def remove_denied_tool(self, tool_name: str) -> bool:
        """移除拒绝工具"""
        if tool_name in self._denied_tools:
            self._denied_tools.discard(tool_name)
            return True
        return False

    def guard(self, tool_name: str, tool_params: Dict[str, Any]) -> ToolGuardResult:
        """守卫工具调用"""
        if not self.enabled:
            return ToolGuardResult(
                tool_name=tool_name,
                safe=True,
                findings=[],
                metadata={"skipped": True, "reason": "engine_disabled"},
            )

        all_findings: List[GuardFinding] = []

        # 检查拒绝列表
        if tool_name in self._denied_tools:
            all_findings.append(
                GuardFinding(
                    rule_id="denied_tool",
                    severity=GuardSeverity.CRITICAL,
                    category=GuardThreatCategory.PRIVILEGE_ESCALATION,
                    message=f"工具 {tool_name} 在拒绝列表中",
                    suggestion="联系管理员将工具从拒绝列表中移除",
                )
            )

        # 构建工具输入文本
        tool_input = self._build_tool_input(tool_name, tool_params)

        # 运行所有守护者
        for guardian in self.guardians:
            try:
                findings = guardian.guard(tool_input, tool_params)
                all_findings.extend(findings)
            except Exception as e:
                logger.warning("守护者 %s 异常: %s", guardian.name, e)

        # 根据审批模式判断安全性
        safe = self._evaluate_safety(all_findings)

        result = ToolGuardResult(
            tool_name=tool_name,
            safe=safe,
            findings=all_findings,
        )

        if not safe:
            logger.warning("工具守卫阻止: %s, " f"发现 %s 个问题", tool_name, len(all_findings))

        return result

    def _build_tool_input(self, tool_name: str, tool_params: Dict[str, Any]) -> str:
        """构建工具输入文本"""
        parts = [tool_name]
        for key, value in tool_params.items():
            parts.append(f"{key}={value}")
        return " ".join(str(p) for p in parts)

    def _evaluate_safety(self, findings: List[GuardFinding]) -> bool:
        """评估安全性"""
        if not findings:
            return True

        severity_order = {
            GuardSeverity.CRITICAL: 4,
            GuardSeverity.HIGH: 3,
            GuardSeverity.MEDIUM: 2,
            GuardSeverity.LOW: 1,
            GuardSeverity.INFO: 0,
        }

        max_severity = max(severity_order.get(f.severity, 0) for f in findings)

        if self.approval_mode == ApprovalMode.STRICT:
            # 严格模式：中等及以上风险阻止
            return max_severity < severity_order[GuardSeverity.MEDIUM]
        elif self.approval_mode == ApprovalMode.AUTO:
            # 自动模式：高风险及以上阻止
            return max_severity < severity_order[GuardSeverity.HIGH]
        else:
            # 手动模式：不自动阻止
            return True

    def should_approve(self, result: ToolGuardResult) -> bool:
        """是否应该批准执行"""
        if result.safe:
            return True

        if self.approval_mode == ApprovalMode.MANUAL:
            # 手动模式：即使不安全也返回 True，等待人工审批
            return True

        # 其他模式：不安全则不批准
        return False
