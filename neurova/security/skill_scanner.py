"""
Neurova 技能扫描器 (Skill Scanner) 2.0

在技能启用前扫描安全威胁，检测恶意代码。
结合智能缓存和白名单机制。
"""

from __future__ import annotations

import datetime
import hashlib
import json
from neurova.core.logger import get_logger
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

logger = get_logger(__name__)


class ScanMode(str, Enum):
    """扫描模式"""

    QUICK = "quick"  # 快速扫描（只扫描主要文件）
    FULL = "full"  # 完整扫描（扫描所有文件）
    DEEP = "deep"  # 深度扫描（包括依赖分析）


class ScanPolicy(str, Enum):
    """扫描策略"""

    ALLOW = "allow"  # 允许通过
    WARN = "warn"  # 发出警告但允许
    DENY = "deny"  # 拒绝执行


@dataclass
class Finding:
    """扫描发现"""

    rule_id: str = ""
    severity: str = "info"  # critical, high, medium, low, info
    message: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    suggestion: Optional[str] = None
    #: 规则族（ScanRule.category / prompt_injection / 空＝元项）。
    #: 「这条能不能参与 DENY」由它与落点文件类型一起决定，见 isDenyBearing。
    category: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }
        if self.file_path:
            result["file_path"] = self.file_path
        if self.line_number is not None:
            result["line_number"] = self.line_number
        if self.evidence:
            result["evidence"] = self.evidence
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.category:
            result["category"] = self.category
        return result


#: 文档与资产类后缀：内容里的示例路径/示例代码不是会被执行的字节（§6-189 裁定甲）。
#: 本仓自带的 presentation-studio 资产包就是被 path_traversal 在 .md 与
#: template-registry.json 的相对链接上误拦的那一类。
DOC_ASSET_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
})

#: 只在「这段字节会被执行/落地」时才有裁决意义的规则族——落在文档类文件上降为**报告项**。
#: 名单外的一律按严：提示注入不依赖代码执行（SKILL.md 正是它的主载体，P1-6 那次修复不撤销），
#: 元项（如 no_files）来源不明也不能被放宽。
CODE_SHAPE_CATEGORIES = frozenset({
    "code_execution", "system_call", "command_injection", "import",
    "network", "file_operation", "path_traversal", "obfuscation", "malware",
})

#: 名称级规则族（`artifact_name`）：判的是**文件名与后缀**，不是内容。它不进上面那张表，
#: 于是 `isDenyBearing` 恒判参与 DENY——`.env` 哪怕一行可读内容也没有也是泄漏，
#: 「这个后缀算不算文档」跟它泄不泄密无关（§6-194 裁定甲″）。
ARTIFACT_NAME_CATEGORY = "artifact_name"

#: 只出读数、永不参与 DENY 的类目。「没扫到」不等于「扫出危险」——把前者当后者，
#: 每个带图片的技能都会被误拒，这道门反而会被人整个关掉。
UNSCANNED_CATEGORY = "unscanned_artifact"
REPORT_ONLY_CATEGORIES = frozenset({UNSCANNED_CATEGORY})

#: 已知凭据/私钥产物的文件名（精确匹配，不按子串——按子串会把 `design_tokens.json`、
#: `password-hash.json` 这类正当资产名一起冤枉掉，实测第一方资产包里 4 个名字中枪）。
CREDENTIAL_BASENAMES = frozenset({
    ".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "git-credentials",
    "credentials", "credentials.json", "credentials.yml", "credentials.yaml",
    "serviceaccount.json", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
CREDENTIAL_SUFFIXES = frozenset({".pem", ".key", ".ppk", ".p12", ".pfx", ".kdbx"})
#: 凭据库目录（相对技能根的路径分段）。`.git` 不在其列：它是仓库产物而非密钥，
#: 开发中的技能目录里带 `.git` 是常态，拦它等于误拦。
SECRET_STORE_DIR_MARKERS = frozenset({".ssh", ".aws", ".gnupg"})
EXECUTABLE_SUFFIXES = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".msi", ".scr", ".elf", ".ocx",
})
#: 内容扫描读哪些后缀（单源，P1-6）。不在表内的文件不会「没问题」，而是「没被读」——
#: 后者由 `unscanned_artifact` 报告项显式记账（§6-194）。
SCANNABLE_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".sh", ".bat", ".ps1",
})
#: 普查时一并跳过的缓存目录（内容扫描本来也不读它们，报出来只会淹没真信号）。
CENSUS_IGNORED_DIRS = frozenset({"__pycache__", "node_modules"})


def isDenyBearing(finding: "Finding") -> bool:
    """这一条发现是否参与 DENY（口径唯一，装载侧不得另写一份）。"""
    if finding.category in REPORT_ONLY_CATEGORIES:
        return False
    if finding.category not in CODE_SHAPE_CATEGORIES:
        return True
    path = finding.file_path or ""
    if not path:
        return True
    return Path(path).suffix.lower() not in DOC_ASSET_SUFFIXES


#: 各策略下"够格决定这次结果"的严重度阈值。**资格**由 `isDenyBearing` 判，**够不够格**由这张表判，
#: 两件事合在一处只算一次（旧实现把 `critical/high` 这个名单在 `passed` 与
#: `blocking_rule_count` 两处各写一遍，改一处就漂一处）。
BLOCKING_SEVERITIES = {
    ScanPolicy.DENY: frozenset({"critical", "high"}),
    ScanPolicy.WARN: frozenset({"critical"}),
}


def isBlocking(finding: "Finding", policy: ScanPolicy = ScanPolicy.DENY) -> bool:
    """这条发现是否**实际决定**这次扫描的结果（ deny-bearing ＋ 达到该策略的严重度阈值）。"""
    if policy == ScanPolicy.ALLOW:
        return False
    return isDenyBearing(finding) and finding.severity in BLOCKING_SEVERITIES[policy]


def blockingFindings(result: "ScanResult") -> List["Finding"]:
    """这次扫描里实际决定结果的条目——**拒因文本只能由它生成**（§6-259）。

    旧版 `scan_skill_for_install` 的 `error` 取的是 `findings[:5]`，于是被念出去的"拒因"里
    混着不参与裁决的读数（文档侧的相对链接等）：读的人会照着去改资产文档，方向全错。
    """
    raw = (result.metadata or {}).get("scan_policy")
    policy = ScanPolicy(raw) if raw in {p.value for p in ScanPolicy} else ScanPolicy.DENY
    return [f for f in result.findings if isBlocking(f, policy)]


@dataclass
class ScanResult:
    """扫描结果"""

    skill_id: str = ""
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    scan_mode: ScanMode = ScanMode.QUICK
    content_hash: Optional[str] = None
    scanned_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    scan_duration: float = 0.0
    file_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        severity_counts: Dict[str, int] = {}
        for f in self.findings:
            severity_counts[f"{f.severity}_count"] = severity_counts.get(f"{f.severity}_count", 0) + 1

        return {
            "skill_id": self.skill_id,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "scan_mode": self.scan_mode.value,
            "content_hash": self.content_hash,
            "scanned_at": self.scanned_at.isoformat(),
            "scan_duration": self.scan_duration,
            "file_count": self.file_count,
            "finding_count": len(self.findings),
            **severity_counts,
        }


@dataclass
class SkillFile:
    """技能文件"""

    path: str = ""
    content: str = ""
    hash: str = ""
    size: int = 0
    file_type: str = "unknown"

    def __post_init__(self):
        if not self.size and self.content:
            self.size = len(self.content)
        if not self.hash and self.content:
            self.hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass
class ScanRule:
    """扫描规则"""

    rule_id: str = ""
    name: str = ""
    pattern: str = ""
    severity: str = "medium"
    message: str = ""
    description: str = ""
    enabled: bool = True
    category: str = "general"
    suggestion: Optional[str] = None
    #: 命中成立的**第二个条件**：同一行是否出现"这段路径会被拿去读/写/解包"的形态。
    #: 为什么要有它（§6-259）：行级正则只看字节，看不见语义——旧版 `dangerous_path_traversal`
    #: 把 `.mjs` 的 ES 相对导入 `from "../…/runtime_helpers.mjs"` 和数据字面量里的
    #: `"../assets/slide-01.png"` 都判成 high 级攻击并参与 DENY（真资产包里光这两形就 60+ 条）。
    #: 真防线在 `security/safe_archive.py::_resolve_within`（成员名归一化后仍须在目标目录内），
    #: 这条行级正则只是**信号**；信号打在无害形态上只会淹没真信号。
    context_pattern: str = ""
    #: 第二个条件没满足时**降到这个严重度照常上报**，不把读数删掉——批 37 定的口径是
    #: "放行≠删发现"，报告面与审计面都得继续看得见这条相对路径引用。
    context_miss_severity: str = "low"
    _compiled: Optional[Pattern] = field(default=None, repr=False)
    _compiled_context: Optional[Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        if self.pattern:
            try:
                self._compiled = re.compile(self.pattern, re.IGNORECASE)
            except re.error:
                self._compiled = None
        if self.context_pattern:
            try:
                self._compiled_context = re.compile(self.context_pattern, re.IGNORECASE)
            except re.error:
                self._compiled_context = None

    def severityFor(self, text: str) -> Optional[str]:
        """这一行的结论：不命中 None；命中但缺上下文 ⇒ 降级严重度；否则按本条严重度。"""
        if not self._compiled or not self.enabled or not self._compiled.search(text):
            return None
        if self._compiled_context is not None and not self._compiled_context.search(text):
            return self.context_miss_severity
        return self.severity

    def matches(self, text: str) -> bool:
        return self.severityFor(text) is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "pattern": self.pattern,
            "severity": self.severity,
            "message": self.message,
            "enabled": self.enabled,
            "category": self.category,
        }


class BaseAnalyzer:
    """分析器基类"""

    @property
    def name(self) -> str:
        raise NotImplementedError

    def analyze(self, skill_file: SkillFile) -> List[Finding]:
        raise NotImplementedError


class PromptInjectionAnalyzer(BaseAnalyzer):
    """提示注入签名分析器（P1-6：中英双语）。

    检测技能文件（SKILL.md/提示词模板）中试图劫持 LLM 行为的内容——
    与"可执行代码"类规则互补：注入不依赖代码执行，纯文本即可生效。
    """

    # (rule_id, 编译正则, 建议处置)
    INJECTION_PATTERNS = [
        ("inject_override_en", r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "删除覆盖系统指令的内容"),
        ("inject_disregard_en", r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions|system\s+prompt|rules)", "删除无视系统提示的内容"),
        ("inject_reveal_prompt_en", r"(print|show|reveal|repeat|output)\s+(your\s+)?(system\s+prompt|instructions)", "删除套取系统提示的内容"),
        ("inject_devmode_en", r"(developer|god|dan)\s+mode", "删除越权模式切换内容"),
        ("inject_roleplay_jailbreak", r"pretend\s+(you\s+are|to\s+be)\s+(an?\s+)?(unrestricted|uncensored)", "删除越狱角色扮演内容"),
        ("inject_override_zh", r"忽略(之前|上面|以上|先前)的?(所有)?(指令|提示|规则)", "删除覆盖系统指令的内容"),
        ("inject_disregard_zh", r"(无视|不要理会|无需遵守)(你的)?(系统提示|系统指令|之前的?指令|规则|限制)", "删除无视系统提示的内容"),
        ("inject_no_restrict_zh", r"(没有|解除|不设|无)(任何)?限制", "删除解除限制的内容"),
        ("inject_reveal_prompt_zh", r"(输出|打印|泄露|透露|告诉我)(你的)?(系统提示词?|初始指令|设定)", "删除套取系统提示的内容"),
        ("inject_devmode_zh", r"(开发者|上帝|越狱)模式", "删除越权模式切换内容"),
        ("inject_exfiltrate", r"(把|将|发送).{0,20}(系统提示|密钥|凭据|token|密码).{0,20}(发送|发到|传到|泄露)", "删除数据外传内容"),
    ]

    def __init__(self):
        self._compiled = [
            (rid, __import__("re").compile(pattern, __import__("re").IGNORECASE), suggestion)
            for rid, pattern, suggestion in self.INJECTION_PATTERNS
        ]

    @property
    def name(self) -> str:
        return "prompt_injection"

    def analyze(self, skill_file: SkillFile) -> List[Finding]:
        findings: List[Finding] = []
        lines = skill_file.content.splitlines()
        for rid, pattern, suggestion in self._compiled:
            for lineno, line in enumerate(lines, start=1):
                m = pattern.search(line)
                if m:
                    findings.append(
                        Finding(
                            rule_id=rid,
                            severity="critical",
                            category="prompt_injection",
                            message=f"检测到提示注入内容（{rid}）",
                            file_path=skill_file.path,
                            line_number=lineno,
                            evidence=line.strip()[:200],
                            suggestion=suggestion,
                        )
                    )
        return findings


class PatternAnalyzer(BaseAnalyzer):
    """模式分析器：基于正则表达式检测危险模式"""

    #: 路径"要拿去读/写/解包/落地"的调用形态——`dangerous_path_traversal` 只在同一行出现这些
    #: 形态时才成立（§6-259，与 `ScanRule.context_pattern` 同一件事）。
    #: **模块说明符故意不在名单里**：ES/CJS 的 `from "../x.mjs"`、`import()`、`require()` 走的是
    #: 模块解析，不是把路径交给文件系统；旧版把它们判成攻击，一只资产包里光这一形就贡献 2 条 high。
    #: 真防线在 `security/safe_archive.py::_resolve_within`（成员名归一化后仍须在目标目录内，显式拦
    #: `..`），这条行级正则只是信号。
    FS_PATH_API_PATTERN = "(" + "|".join((
        r"\bopen\s*\(",
        r"\bPath\s*\(",
        r"\bjoinpath\s*\(",
        r"\bos\.path\.\w+\s*\(",
        r"\bos\.(?:remove|unlink|rename|replace|mkdir|makedirs|listdir|scandir|chdir|startfile)\s*\(",
        r"\bshutil\.\w+\s*\(",
        r"\b(?:read|write)_(?:text|bytes)\s*\(",
        r"\b(?:glob|rglob)\s*\(",
        r"\bextract(?:all|file)?\s*\(",
        r"\bsendfile\s*\(",
        r"\b(?:mkdir|rmdir|unlink|rename|replace|truncate|stat|touch|copyfile|copy2|copytree|copy|rmtree|move)\s*\(",
        r"\b(?:readFile|writeFile|appendFile|createReadStream|createWriteStream)Sync?\s*\(",
        r"\b(?:mkdirSync|rmSync|unlinkSync|renameSync|copyFileSync|rmdirSync)\s*\(",
        r"\bpath\.(?:join|resolve|normalize)\s*\(",
    )) + ")"

    def __init__(self):
        self.rules: Dict[str, ScanRule] = {}
        self._load_default_rules()

    @property
    def name(self) -> str:
        return "pattern_analyzer"

    def _load_default_rules(self):
        """加载默认规则"""
        default_rules = [
            ScanRule(
                rule_id="dangerous_exec",
                name="危险执行函数",
                # 只判**裸名调用**：`exec(`/`eval(`/`compile(`。旧形态 `\b(exec|eval|compile)\s*\(`
                # 里 `\b` 在 `.` 与 `c` 之间同样成立 ⇒ `re.compile(` 被当成 critical 级危险执行，
                # 仓内自带资产包里 27 条命中有 26 条是正则预编译（§6-250），门就此把"任何带正则的
                # 技能包"一律拒掉。属性调用（`re.compile(`、`cursor.exec(`）不是内置动态执行。
                pattern=r"(?<![\w.])\b(exec|eval|compile)\s*\(",
                severity="critical",
                message="检测到危险的代码执行函数调用",
                category="code_execution",
                suggestion="避免使用 exec/eval，使用更安全的替代方案",
            ),
            ScanRule(
                rule_id="os_system",
                name="os.system 调用",
                pattern=r"\bos\.system\s*\(",
                severity="high",
                message="检测到 os.system 系统命令调用",
                category="system_call",
                suggestion="使用 subprocess.run 并验证输入",
            ),
            ScanRule(
                rule_id="subprocess_call",
                name="subprocess 调用",
                pattern=r"\bsubprocess\.(call|run|Popen|check_output|check_call)\s*\(",
                severity="high",
                message="检测到 subprocess 系统命令调用",
                category="system_call",
                suggestion="确保命令参数经过验证",
            ),
            ScanRule(
                rule_id="shell_true",
                name="shell=True",
                pattern=r"shell\s*=\s*True",
                severity="high",
                message="检测到 shell=True 参数，可能导致命令注入",
                category="command_injection",
                suggestion="避免 shell=True，使用参数列表方式",
            ),
            ScanRule(
                rule_id="dangerous_import_subprocess",
                name="导入 subprocess",
                pattern=r"^import\s+subprocess",
                severity="medium",
                message="导入了 subprocess 模块",
                category="import",
            ),
            ScanRule(
                rule_id="dangerous_import_os",
                name="导入 os",
                pattern=r"^import\s+os",
                severity="low",
                message="导入了 os 模块",
                category="import",
            ),
            ScanRule(
                rule_id="network_request",
                name="网络请求",
                pattern=r"\b(requests\.(get|post|put|delete)|urllib\.request\.urlopen|httpx\.(get|post))\s*\(",
                severity="medium",
                message="检测到网络请求调用",
                category="network",
                suggestion="验证请求目标 URL",
            ),
            ScanRule(
                rule_id="file_write",
                name="文件写入",
                pattern=r"\bopen\s*\([^)]*['\"][wa]",
                severity="medium",
                message="检测到文件写入操作",
                category="file_operation",
                suggestion="确保写入路径安全",
            ),
            ScanRule(
                rule_id="dangerous_path_traversal",
                name="路径遍历",
                pattern=r"\.\.[\\/]",
                # 同行要有"把这段路径拿去读/写/解包"的形态才算（见 FS_PATH_API_PATTERN 的理由）
                context_pattern=self.FS_PATH_API_PATTERN,
                severity="high",
                message="检测到潜在的路径遍历攻击",
                category="path_traversal",
            ),
            ScanRule(
                rule_id="base64_decode",
                name="Base64 解码",
                pattern=r"\bbase64\.b64decode\s*\(",
                severity="low",
                message="检测到 Base64 解码，可能隐藏恶意代码",
                category="obfuscation",
            ),
            ScanRule(
                rule_id="crypto_mining",
                name="挖矿代码",
                pattern=r"(coinhive|cryptoloot|coinimp|crypto.*mining)",
                severity="critical",
                message="检测到疑似挖矿代码",
                category="malware",
            ),
            ScanRule(
                rule_id="reverse_shell",
                name="反弹 Shell",
                pattern=r"/bin/(ba)?sh.*-i|nc\s+.*-e\s+/bin/(ba)?sh",
                severity="critical",
                message="检测到疑似反弹 Shell 代码",
                category="malware",
            ),
            ScanRule(
                rule_id="data_exfiltration",
                name="数据外泄",
                pattern=r"(curl|wget|http).*\|.*sh",
                severity="critical",
                message="检测到疑似数据外泄/远程代码执行",
                category="malware",
            ),
        ]

        for rule in default_rules:
            self.rules[rule.rule_id] = rule

    def add_rule(self, rule: ScanRule):
        """添加规则"""
        if rule.rule_id in self.rules:
            logger.debug("规则已存在，覆盖: %s", rule.rule_id)
        self.rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        """移除规则"""
        if rule_id in self.rules:
            del self.rules[rule_id]
            return True
        return False

    def analyze(self, skill_file: SkillFile) -> List[Finding]:
        """分析文件"""
        findings: List[Finding] = []
        if not skill_file.content:
            return findings

        lines = skill_file.content.split("\n")

        for rule in self.rules.values():
            if not rule.enabled:
                continue

            for line_num, line in enumerate(lines, 1):
                severity = rule.severityFor(line)
                if severity is not None:
                    finding = Finding(
                        rule_id=rule.rule_id,
                        severity=severity,
                        category=rule.category,
                        message=rule.message,
                        file_path=skill_file.path,
                        line_number=line_num,
                        evidence=line.strip(),
                        suggestion=rule.suggestion,
                    )
                    findings.append(finding)

        return findings


class ScanCache:
    """扫描结果缓存"""

    def __init__(self, ttl: float = 3600.0):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl

    def _get_cache_key(self, skill_id: str, content_hash: str) -> str:
        return f"{skill_id}:{content_hash}"

    def get(self, skill_id: str, content_hash: str) -> Optional[ScanResult]:
        key = self._get_cache_key(skill_id, content_hash)
        entry = self._cache.get(key)
        if not entry:
            return None

        # 检查 TTL
        if time.time() - entry["timestamp"] > self._ttl:
            del self._cache[key]
            return None

        return entry["result"]

    def set(self, skill_id: str, content_hash: str, result: ScanResult):
        key = self._get_cache_key(skill_id, content_hash)
        self._cache[key] = {
            "result": result,
            "timestamp": time.time(),
        }

    def clear(self):
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)


class WhitelistManager:
    """白名单管理器"""

    def __init__(self, config_path: str = ""):
        # 落点：显式入参 > 数据根下的 `whitelist.json`。原默认值是裸文件名，
        # 一进构造函数就读一个随 CWD 变的路径（读到哪个白名单全看启动目录）。
        from neurova.core.data_root import dataLanding

        self._config_path = Path(config_path) if config_path else dataLanding("whitelist.json")
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """加载白名单"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = data.get("entries", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载白名单失败: %s", e)
                self._entries = {}

    def _save(self):
        """保存白名单"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump({"entries": self._entries}, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error("保存白名单失败: %s", e)

    def is_whitelisted(self, skill_id: str) -> bool:
        return skill_id in self._entries

    def add(self, skill_id: str, hash: str = "", reason: str = ""):
        self._entries[skill_id] = {
            "hash": hash,
            "reason": reason,
            "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._save()

    def remove(self, skill_id: str) -> bool:
        if skill_id in self._entries:
            del self._entries[skill_id]
            self._save()
            return True
        return False

    def clear(self):
        self._entries.clear()
        self._save()

    def size(self) -> int:
        return len(self._entries)

    def list_all(self) -> List[Dict[str, Any]]:
        return [{"skill_id": sid, **info} for sid, info in self._entries.items()]


class SkillScanner:
    """技能扫描器"""

    def __init__(self, workspace_path: str = ".", cache_ttl: float = 3600.0):
        from neurova.core.data_root import dataLanding

        self._workspace_path = Path(workspace_path)
        # 落点归数据根（与 `WhitelistManager` 的 `dataLanding("whitelist.json")` 同源）。
        # 原实现是 `self._workspace_path / ".skill_scanner"`，而 `workspace_path` 的
        # 默认值是 `"."`——相对进程 CWD，于是"扫描器建目录"这件事在仓库根建塔写盘，
        # 落点随 CWD 漂移（构造期定死，逐条用例补 env 治不了）。
        self._config_dir = dataLanding("skillScanner")
        self._config_dir.mkdir(parents=True, exist_ok=True)

        self.policy: ScanPolicy = ScanPolicy.WARN
        self.analyzers: List[BaseAnalyzer] = []
        self._cache = ScanCache(ttl=cache_ttl)
        self._whitelist = WhitelistManager(config_path=str(self._config_dir / "whitelist.json"))
        self._custom_rules: Dict[str, ScanRule] = {}

        # 添加默认模式分析器 + 提示注入分析器（P1-6：中英双语注入签名）
        self.analyzers.append(PatternAnalyzer())
        self.analyzers.append(PromptInjectionAnalyzer())

        logger.info("技能扫描器初始化完成")

    def add_analyzer(self, analyzer: BaseAnalyzer):
        """添加分析器"""
        if analyzer not in self.analyzers:
            self.analyzers.append(analyzer)

    def remove_analyzer(self, analyzer: BaseAnalyzer):
        """移除分析器"""
        if analyzer in self.analyzers:
            self.analyzers.remove(analyzer)

    def add_custom_rule(self, rule: ScanRule):
        """添加自定义规则"""
        self._custom_rules[rule.rule_id] = rule
        # 也添加到模式分析器
        for analyzer in self.analyzers:
            if isinstance(analyzer, PatternAnalyzer):
                analyzer.add_rule(rule)
                break

    def list_builtin_rules(self) -> List[ScanRule]:
        """列出所有内置规则"""
        rules = []
        for analyzer in self.analyzers:
            if isinstance(analyzer, PatternAnalyzer):
                rules.extend(analyzer.rules.values())
        return rules

    def whitelist_skill(self, skill_id: str, hash: str = "", reason: str = ""):
        """将技能加入白名单"""
        self._whitelist.add(skill_id, hash=hash, reason=reason)
        logger.info("技能 %s 已加入白名单", skill_id)

    def is_skill_whitelisted(self, skill_id: str) -> bool:
        """检查技能是否在白名单中"""
        return self._whitelist.is_whitelisted(skill_id)

    def _compute_content_hash(self, content: str) -> str:
        """计算内容哈希"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _discover_files(self, skill_path: str) -> List[SkillFile]:
        """发现技能文件（内容面：只读可扫后缀里的字节）"""
        files: List[SkillFile] = []
        root = Path(skill_path)

        # 可扫描的文件类型见模块级 SCANNABLE_SUFFIXES（单源）。
        # P1-6：.md/.markdown/.txt 必须在列——SKILL.md 是提示注入的主载体，
        # 纯文本注入不依赖代码执行（原白名单漏 .md 属漏洞缺口）
        # §6-194：补 .mjs/.cjs/.mts/.cts。原清单缺它们，实测自带资产包里 37 个 .mjs
        # 从不进扫描——代码形状的字节落在门看不见的后缀里。
        for file_path in sorted(self._enumerateArtifactPaths(skill_path)):
            # 跳过隐藏目录（内容扫描不读前导点目录；名称级普查另走一条，见 _enumerateArtifactPaths）
            if any(p.startswith(".") for p in file_path.relative_to(root).parts):
                continue

            if file_path.suffix.lower() not in SCANNABLE_SUFFIXES:
                continue

            # 跳过过大文件
            if file_path.stat().st_size > 1024 * 1024:  # 1MB
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                sf = SkillFile(
                    path=str(file_path),
                    content=content,
                    file_type=file_path.suffix,
                )
                files.append(sf)
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("无法读取文件 %s: %s", file_path, e)

        return files

    def _enumerateArtifactPaths(self, skill_path: str) -> List[Path]:
        """目录内**全部**文件（含前导点的），只排除缓存目录。

        与 `_discover_files` 的取舍正相反：那张表决定「读谁的内容」，这张表决定
        「谁的名字该被看一眼」——`.env`、`id_rsa` 没有可读内容也照样是泄漏。
        """
        root = Path(skill_path)
        if not root.exists() or not root.is_dir():
            return []
        found: List[Path] = []
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part in CENSUS_IGNORED_DIRS for part in file_path.relative_to(root).parts):
                continue
            found.append(file_path)
        return found

    def _artifactNameFindings(self, skill_path: str, allPaths: List[Path],
                              scannedPaths: set) -> List[Finding]:
        """名称级裁决：凭据/私钥产物、可执行产物、以及「没被读过」这件事本身。"""
        root = Path(skill_path)
        findings: List[Finding] = []
        unscanned: List[str] = []

        for file_path in allPaths:
            rel = file_path.relative_to(root)
            name = file_path.name.lower()
            suffix = file_path.suffix.lower()
            if str(file_path) not in scannedPaths:
                unscanned.append(rel.as_posix())

            if suffix in EXECUTABLE_SUFFIXES:
                findings.append(Finding(
                    rule_id="executable_artifact",
                    severity="high",
                    category=ARTIFACT_NAME_CATEGORY,
                    message=f"技能包含可执行产物: {rel.as_posix()}",
                    file_path=str(file_path),
                    suggestion="技能包只应携带源码与资产，二进制产物无法审计",
                ))
                continue

            reason = ""
            if name in CREDENTIAL_BASENAMES:
                reason = "已知凭据文件"
            elif suffix in CREDENTIAL_SUFFIXES:
                reason = "私钥/证书容器"
            elif any(part.lower() in SECRET_STORE_DIR_MARKERS for part in rel.parts[:-1]):
                reason = "凭据目录下的文件"
            if reason:
                findings.append(Finding(
                    rule_id="credential_artifact_name",
                    severity="high",
                    category=ARTIFACT_NAME_CATEGORY,
                    message=f"技能包含{reason}: {rel.as_posix()}",
                    file_path=str(file_path),
                    suggestion="安装前移除凭据与私钥文件（技能包不得携带用户密钥）",
                ))

        if unscanned:
            findings.append(Finding(
                rule_id="unscanned_artifact",
                severity="medium",
                category=UNSCANNED_CATEGORY,
                message=f"{len(unscanned)} 个文件不在可扫描后缀/大小清单内，内容未经审计",
                evidence=", ".join(unscanned[:10]) + ("…" if len(unscanned) > 10 else ""),
                suggestion="把其后缀纳入 SCANNABLE_SUFFIXES，或改为可读的源码/资产形态",
            ))
        return findings

    def scan_skill(
        self,
        skill_id: str,
        skill_path: str,
        mode: ScanMode = ScanMode.QUICK,
    ) -> ScanResult:
        """扫描技能"""
        start_time = time.time()

        # 检查白名单
        if self._whitelist.is_whitelisted(skill_id):
            logger.info("技能 %s 在白名单中，跳过扫描", skill_id)
            return ScanResult(
                skill_id=skill_id,
                passed=True,
                scan_mode=mode,
                findings=[],
                metadata={"skipped": True, "reason": "whitelisted"},
            )

        # 发现文件（内容面）+ 全量普查（名称面）。两面的取舍正相反：内容面跳过前导点目录，
        # 名称面恰恰要靠这些点认出 `.env`/`.ssh/` 这类凭据产物（§6-194）。
        files = self._discover_files(skill_path)
        allPaths = self._enumerateArtifactPaths(skill_path)
        nameFindings = self._artifactNameFindings(skill_path, allPaths, {f.path for f in files})
        unscannedCount = len(allPaths) - len(files)

        if not files:
            return ScanResult(
                skill_id=skill_id,
                passed=False,
                scan_mode=mode,
                findings=[
                    Finding(
                        rule_id="no_files",
                        severity="high",
                        message=f"技能路径不存在或没有可扫描的文件: {skill_path}",
                    )
                ] + nameFindings,
                file_count=0,
                # 早退也要带上策略：拒因文本由 `blockingFindings` 生成，它读的就是这个键
                metadata={"unscanned_file_count": unscannedCount,
                          "scan_policy": self.policy.value},
            )

        # 计算内容哈希。摘要**必须含文件名普查**：只按可读内容算时，包里多塞一个 `.env`
        # 不改摘要，第二次扫就命中缓存里那条旧的放行结论——门形同虚设。
        census = "\n".join(str(p.relative_to(Path(skill_path)).as_posix()) for p in allPaths)
        all_content = census + "\n" + "\n".join(f.content for f in files)
        content_hash = self._compute_content_hash(all_content)

        # 检查缓存
        cached = self._cache.get(skill_id, content_hash)
        if cached:
            logger.debug("缓存命中: %s", skill_id)
            return cached

        # 执行扫描
        all_findings: List[Finding] = list(nameFindings)

        for skill_file in files:
            for analyzer in self.analyzers:
                findings = analyzer.analyze(skill_file)
                all_findings.extend(findings)

        # 根据策略判断是否通过。文档/资产类文件上的"代码形状"规则**不参与 DENY**，
        # 但发现项原样留在 findings 里（放行≠删读数——报告面与审计面都还看得见）。
        reportOnly = [f.rule_id for f in all_findings if not isDenyBearing(f)]
        blocking = [f for f in all_findings if isBlocking(f, self.policy)]
        if self.policy == ScanPolicy.ALLOW:
            passed = True
        else:
            passed = not blocking

        result = ScanResult(
            skill_id=skill_id,
            passed=passed,
            findings=all_findings,
            scan_mode=mode,
            content_hash=content_hash,
            scan_duration=time.time() - start_time,
            file_count=len(files),
            metadata={"report_only_rules": reportOnly,
                      "unscanned_file_count": unscannedCount,
                      # 阈值随策略走（旧实现不分策略都按 critical/high 数，WARN 下会多报）
                      "blocking_rule_count": len(blocking),
                      "scan_policy": self.policy.value},
        )

        # 缓存结果
        self._cache.set(skill_id, content_hash, result)

        logger.info("技能扫描完成: %s, 通过=%s, " f"文件数=%s, 发现=%s", skill_id, passed, len(files), len(all_findings))

        return result
