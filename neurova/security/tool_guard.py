"""
Neurova 工具守卫 (Tool Guard) 2.0

在 Agent 调用工具前实时检测危险模式，防止恶意操作。
结合 Neurova 的认知增强特性。
"""

from __future__ import annotations

import datetime
import os
from neurova.core.logger import get_logger
from neurova.security.shell_normalization import normalize_posix_line_continuations
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

    #: 该守护者吃哪一面扫描输入：
    #:   "all"     ＝工具名＋全部参数值的整串（默认；新增 guardian 不声明就不掉覆盖面）
    #:   "command" ＝只喂命令语义的输入：路径键的值仅在"整串就是一个路径"时被豁免（§6-255 甲案）
    #: 豁免是白名单式的，判不准就当命令扫——收窄的方向永远是保守的。
    scan_surface: str = "all"

    @property
    def name(self) -> str:
        raise NotImplementedError

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        raise NotImplementedError


# ── 参数语义两把键清单（§6-255 甲案，全仓唯一出处）─────────────────────────────
# 治理预检（`governance.extract_adjudicable_params`）与守卫扫描面**都从这里取数**。
# 此前 governance.py 另抄了一份 `_ADJUDICABLE_COMMAND_KEYS`／`_ADJUDICABLE_PATH_KEYS`，
# 同一个问题（"哪些参数是命令、哪些是路径"）有两个答案，改一处另一处静默不跟（教义第 6 条）。
COMMAND_PARAM_KEYS = ("command", "code")

#: 「哪些名字指向路径语义」的**唯一出处**：一个名字在这件事上可以扮演四种角色，
#: 下面每个消费方各取自己那一份投影，不再各自写字面（§6-284 第②刀前半）。
#: 本表**只统一来源，不改裁决**——四角色的划分就是改前三份名单的实状：
#:   scanned      值按键名从参数面取来扫路径面，并从命令扫描面剔除（§6-266 第①刀裁的就是这一族）
#:   textual      仅当 scanned 一支取不到时，才在扁串里按 `k=v` 抠值（原回落正则的字面键）
#:   alias_plain  LLM 常产出的无歧义别名，直接归一到规范名（原 UNAMBIGUOUS_ALIASES）
#:   alias_gated  可能与真实参数名撞车、须 schema 背书的别名（原 SCHEMA_REQUIRED_ALIASES 的路径族）
#: 顺序有意义：`pathNamesWithRole` 保持声明顺序，而"取哪条路径"正是由 scanned 清单的**顺序**定的。
#: "到底该按哪张表判"（按 schema 判 vs 扩清单）是下一批要拍的；拍之前，分歧在本文件一处可见、
#: 且由 `tests/unit/security/test_pathNameListsDerivedFromOneTable.py` 逐名钉住。
PATH_CANONICAL_NAME = "file_path"
PATH_NAME_ROLES = {
    "file_path": ("scanned",),
    "path":      ("scanned", "textual", "alias_gated"),
    "file":      ("textual", "alias_gated"),
    "dir":       ("textual",),
    "filename":  ("alias_plain",),
    "filepath":  ("alias_plain",),
    "filePath":  ("alias_plain",),
    "file_name": ("alias_plain",),
    "fileName":  ("alias_plain",),
}


def pathNamesWithRole(role: str) -> tuple:
    """单源表的一个投影（消费方只许经此取数，不许再写字面）。"""
    return tuple(name for name, roles in PATH_NAME_ROLES.items() if role in roles)


#: 键名清单（与改前逐项同序）：治理预检与命令面剔除都读它。
PATH_PARAM_KEYS = pathNamesWithRole("scanned")
#: 扁串回落那一支的取值式，由 textual 角色派生（原字面 `(?:path|file|dir)=([^\s]+)`）。
#: 只剩「调用方没把参数面交出来」这一种场合用它——按空格猜值边界会把带空格的路径切短。
PATH_VALUE_PATTERN = re.compile(r"(?:%s)=([^\s]+)" % "|".join(pathNamesWithRole("textual")))


def pathValuesFromParams(params: Any) -> List[tuple]:
    """参数面上**每一个**登记为路径语义的键值，成 `(键名, 值)` 返回——逐值裁决的唯一取数口。

    名字集是单源表两个角色的投影（`scanned` ∪ `textual`，`path` 同时挂在两个角色上，只算一次），
    本函数不新增也不删改任何名字：扩清单与"按 schema 判"（§6-284 的丁）都不在这一刀里。
    过去这条问句有两个各写一份的实现——咽喉里「取到第一个非空就 break」，治理预检里
    `next(...)` 再取一次第一个——于是同一次调用里的第二条路径参数在两处都消失（§6-284 甲案）。
    按 `looksLikePathValue` 挑值的另一种问句（"这个串长得像不像路径"）不在这里，那是扫描面剔除的口径。
    """
    if not isinstance(params, dict):
        return []
    names = list(dict.fromkeys(tuple(pathNamesWithRole("scanned"))
                               + tuple(pathNamesWithRole("textual"))))
    out: List[tuple] = []
    for name in names:
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            out.append((name, value))
    return out

#: 路径值里"shell 会另作解释"的字符——命中任一即由 `FilePathGuardian` 出一条 low 级审计读数。
#: 这一族**只用于报告面**：§6-266 第①刀裁定之前它还兼作豁免闸（含这些字符就不豁免），于是同一个
#: 值按键名是路径、按字符又被当命令扫一遍——两个答案。裁定后只留一个：**键名语义决定扫描面**。
#: 通配 `*` `?` 不在表内——那是 `wildcard_path` 已有的 MEDIUM 读数，重复报只会淹没真信号。
_SHELL_EXECUTION_PATTERN = re.compile(r"[;|&`$<>\"'{}\n\r\t]")
_ABSOLUTE_PATH_SHAPE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~[\\/])")
_PATH_SEPARATOR = re.compile(r"[/\\]")


def looksLikePathValue(value: Any) -> bool:
    """整串就是一个路径 → 该值按**路径语义**裁决，不进命令语义扫描面。

    只看形状：绝对路径（POSIX／Windows 盘符或 UNC／`~`）或含分隔符的相对路径。
    形状之外不再设字符否决——反斜杠是 Windows 的路径分隔符，`$` `;` 引号是合法文件名里的字符，
    把它们当"这条不是路径"的证据，就是把同一个键的两种语义混在一处判。
    「按路径待它」不等于「放过」：值里出现 shell 会另作解释的字符时，由
    `carriesShellSemantics` 供 `FilePathGuardian` 出一条 low 级读数（报告面看得见，不参与 DENY）。
    """
    if not isinstance(value, str) or not value.strip():
        return False
    return bool(_ABSOLUTE_PATH_SHAPE.match(value) or _PATH_SEPARATOR.search(value))


def carriesShellSemantics(value: Any) -> bool:
    """这串值里是否出现 shell 会另作解释的字符——供审计点名，不作豁免判据。"""
    if not isinstance(value, str):
        return False
    return bool(_SHELL_EXECUTION_PATTERN.search(value))


class RuleBasedToolGuardian(BaseGuardian):
    """基于规则的工具守护者

    规则全是**命令形态**（`rm -rf`、`chmod 777`、`git push`、`curl | sh`…），
    故只吃命令面：路径键里的无害整串值不参与匹配（§6-255 甲案）。
    """

    scan_surface = "command"

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
            # ── P0-3 git 工具族治理（裁决根因位置，执行体内零策略守卫）──
            # 写动词 → HIGH（生产 ask_on_high=True 即 ASK 弹窗确认）；
            # 读动词（status/diff/log/show/blame/ls-files…）不命中 → 放行。
            # 按命令文本命中：git 工具与 computer_shell 跑 git 同受此规则（一致性）。
            ToolGuardRule(
                rule_id="git_write_operation",
                name="Git 写操作",
                pattern=(
                    r"\bgit\s+(add|commit|push|pull|fetch|clone|checkout|switch|restore"
                    r"|merge|rebase|reset|revert|cherry-pick|stash|tag|clean|am|apply|init"
                    r"|mv|rm|worktree|submodule|gc|prune|filter-branch|remote|config)\b"
                    r"|\bgit\s+branch\s+-[dDmM]\b"
                ),
                severity=GuardSeverity.HIGH,
                category=GuardThreatCategory.DESTRUCTIVE_COMMAND,
                message="Git 写操作需人工确认（变更仓库状态）",
            ),
            # RCE / 持久化劫持形态：通过全局配置键（core.pager/editor/fsmonitor/
            # sshCommand…）、config --global/--system 持久化、--exec-path 替换、
            # GIT_* 执行环境注入，把只读 git 变成命令执行。一律 CRITICAL 阻断。
            ToolGuardRule(
                rule_id="git_rce_vectors",
                name="Git 执行劫持",
                pattern=(
                    r"\bgit\s+(-c|--config-env)\s+\S*(?:core\.(?:pager|editor|fsmonitor"
                    r"|sshCommand|ssh_command|attributesFile|hooksPath|repositoryformatversion"
                    r"|ignoreCase)|sequence\.editor|mergetool\..*cmd|difftool\..*cmd|help\..*)"
                    r"|\bgit\s+config\s+--(?:global|system|file)\b"
                    r"|\bgit\s+--exec-path(?:=|\s)"
                    r"|\bGIT_(?:SSH_COMMAND|SSH|PROXY_COMMAND|EXTERNAL_DIFF|CUSTOM_COMMITTER|DIR)\s*="
                ),
                severity=GuardSeverity.CRITICAL,
                category=GuardThreatCategory.COMMAND_INJECTION,
                message="Git 命令含执行劫持/持久化配置注入特征，已阻断",
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
    """Shell 逃逸检测守护者

    检测的是 shell 的转义/替换/管道写法，只在命令语义上有意义：
    `C:\\Users\\xccoo\\a.txt` 里的 `\\xcc` 是路径分隔符加用户名，不是十六进制转义（§6-255）。
    """

    scan_surface = "command"

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
            # `\uNNNN` 这条原先只活在两个零调用的 helper 里（＝等于不存在）。§6-266 第③刀
            # 按教义第 7 条把它并进主表，严重度取齐同族（`$()`／反引号／`\xNN`／base64 全 HIGH），
            # 不分叉成第二档口径。路径键的值不进命令面（第①刀换向），所以 `C:\Users\u1234\…`
            # 不会被读成转义——这条能力落地不带回 §6-255 那条老病。
            (r"\\u[0-9a-fA-F]{4}", GuardSeverity.HIGH, GuardThreatCategory.SHELL_EVASION,
             "Unicode 编码"),
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

    def _scan_protected_paths_in_text(self, text: str) -> List["GuardFinding"]:
        """在命令文本中扫描受保护路径（路径段边界匹配，防 /usr/root 类误报）。"""
        findings: List[GuardFinding] = []
        candidates = list(self._protected_paths)
        for prefix in self._windows_protected_prefixes:
            candidates.append(prefix)
        seen = set()
        for protected in candidates:
            pattern = (
                r"(?<![\w./\\-])" + re.escape(protected) + r"(?![\w.\-])"
            )
            if re.search(pattern, text, re.IGNORECASE) and protected not in seen:
                seen.add(protected)
                findings.append(
                    GuardFinding(
                        rule_id="protected_path_in_command",
                        severity=GuardSeverity.HIGH,
                        category=GuardThreatCategory.PATH_TRAVERSAL,
                        message=f"命令访问受保护路径: {protected}",
                        evidence=protected,
                        suggestion=f"路径 {protected} 受系统保护，命令方式访问同样受限",
                    )
                )
        return findings

    def guard(self, tool_input: str, context: Dict[str, Any]) -> List[GuardFinding]:
        """检查文件路径安全性——§6-284 甲案：**每一个**路径值都判，命令文本恒常扫。

        取数只经 `pathValuesFromParams`（名字集是单源表 scanned∪textual 的投影，这个方法不再自己
        认键）；过去是「取到第一个非空就 break」，于是一次调用里第二条路径参数从不被查。
        `tool_input` 扁串那支只在**参数面一个路径值都没有**时才用——按空格猜值边界会把
        `C:\\Program Files\\...` 切成 `C:\\Program`，能不走它就绪不走它。
        """
        pairs = pathValuesFromParams(context)
        if not pairs:
            # 参数面一个路径值都没有，才回落到扁串里那支 `k=v` 形状（名字集同出一张表）。
            # 按空格猜值边界会把 `C:\Program Files\...` 切成 `C:\Program`——所以参数面在场时
            # 一律走上面那条，这一支只留给"值只在扫描面里"的场合。
            path_match = PATH_VALUE_PATTERN.search(tool_input)
            if path_match:
                pairs = [("", path_match.group(1))]

        findings: List[GuardFinding] = []
        judged: Set[str] = set()
        for _key, value in pairs:
            if value in judged:
                continue
            judged.add(value)
            findings.extend(self._checkOnePath(value))

        # P0-1 同根因族补口：受保护路径出现在命令文本内（如 `cat /etc/passwd`）也须覆盖。
        # 这一支过去挂在 `if not path:` 下面，于是"带 path 参数的 shell 调用"里命令行写的受保护
        # 路径从不被查（case 2）。它按**文本**裁决，与上面按**值**裁决是两个归属，互不去重。
        command_text = context.get("command") if isinstance(context, dict) else None
        if isinstance(command_text, str) and command_text:
            findings.extend(self._scan_protected_paths_in_text(command_text))
        return findings

    def _checkOnePath(self, path: str) -> List[GuardFinding]:
        """对**一个**路径值跑完整判定——规则顺序与 rule_id 与改前逐字一致（单路径读数不许变）。"""
        findings: List[GuardFinding] = []

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

        # §6-266 第①刀（用户裁"按路径语义待它"）：路径键的值不再因这些字符被回命令面扫一遍，
        # 但"这串里带 shell 会另作解释的字符"必须留痕。low 不参与 DENY（AUTO 拦 ≥HIGH、
        # STRICT 拦 ≥MEDIUM），审计面与审批卡仍看得见这条——批 37 的"降级不删读数"口径。
        if carriesShellSemantics(path):
            findings.append(
                GuardFinding(
                    rule_id="path_with_shell_metacharacters",
                    severity=GuardSeverity.LOW,
                    category=GuardThreatCategory.PATH_TRAVERSAL,
                    message=f"路径值含 shell 会另作解释的字符: {path}",
                    evidence=path,
                    suggestion="本条按路径语义裁决，不参与拦截；若工具实现要把这个参数拼进命令行，"
                             "请改用参数数组或先转义，别依赖扫描器替它兜住",
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

        # P0-1：POSIX shell 分词前移除 \+换行续行，
        # 守卫必须看归一化后的命令形态，否则敏感路径/逃逸特征被物理换行
        # 拆开即可绕过。result.metadata 保留原文供日志审计。
        # 命令语义的键取自单源清单 COMMAND_PARAM_KEYS（此处原先硬写一个 "command"，
        # 同属命令语义的 `code` 就漏了归一化——两处口径分叉的同族形状）。
        guard_params = tool_params
        normalizedFrom: Dict[str, str] = {}
        if isinstance(tool_params, dict):
            for key in COMMAND_PARAM_KEYS:
                value = tool_params.get(key)
                if isinstance(value, str):
                    folded = normalize_posix_line_continuations(value)
                    if folded != value:
                        normalizedFrom[key] = folded
            if normalizedFrom:
                guard_params = {**tool_params, **normalizedFrom}

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

        # 构建工具输入文本，并按 guardian 声明的语义分两面（§6-255 甲案）：
        # 命令语义的 guardian 不吃"路径键里的纯路径值"，全量面照旧。
        tool_input = self._build_tool_input(tool_name, guard_params)
        command_input = self._build_command_surface(tool_name, guard_params)

        # 运行所有守护者
        for guardian in self.guardians:
            surface = command_input if guardian.scan_surface == "command" else tool_input
            try:
                findings = guardian.guard(surface, guard_params)
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
        if normalizedFrom:
            result.metadata["normalized_command"] = True
            result.metadata["original_command"] = tool_params.get(next(iter(normalizedFrom)))

        if not safe:
            logger.warning("工具守卫阻止: %s, " f"发现 %s 个问题", tool_name, len(all_findings))

        return result

    def _build_tool_input(self, tool_name: str, tool_params: Dict[str, Any]) -> str:
        """构建工具输入文本"""
        parts = [tool_name]
        for key, value in tool_params.items():
            parts.append(f"{key}={value}")
        return " ".join(str(p) for p in parts)

    def _build_command_surface(self, tool_name: str, tool_params: Dict[str, Any]) -> str:
        """命令语义扫描面：从整串输入里剔除"确实是一个路径"的路径键值（§6-255 甲案／§6-266 第①刀）。

        剔除条件只看两件事：键在 `PATH_PARAM_KEYS` 里，且值过 `looksLikePathValue`（形状）。
        **字符不再决定豁免**——含 `$` `;` 引号的合法文件名照样按路径语义走，改由
        `FilePathGuardian` 出一条 low 级 `path_with_shell_metacharacters` 读数落进审计面。
        没登记进任何一把清单的键一律照命令面扫（那是仍然保守的那一侧）。
        """
        parts = [tool_name]
        for key, value in tool_params.items():
            if key in PATH_PARAM_KEYS and looksLikePathValue(value):
                continue
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
