"""
Neurova 技能扫描器 (Skill Scanner) 2.0

在技能启用前扫描安全威胁，检测恶意代码。
结合智能缓存和白名单机制。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)


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
        return result


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


class PatternAnalyzer(BaseAnalyzer):
    """模式分析器：基于正则表达式检测危险模式"""

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
                pattern=r"\b(exec|eval|compile)\s*\(",
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
                if rule.matches(line):
                    finding = Finding(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
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

    def __init__(self, config_path: str = "whitelist.json"):
        self._config_path = Path(config_path)
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
        self._workspace_path = Path(workspace_path)
        self._config_dir = self._workspace_path / ".skill_scanner"
        self._config_dir.mkdir(parents=True, exist_ok=True)

        self.policy: ScanPolicy = ScanPolicy.WARN
        self.analyzers: List[BaseAnalyzer] = []
        self._cache = ScanCache(ttl=cache_ttl)
        self._whitelist = WhitelistManager(config_path=str(self._config_dir / "whitelist.json"))
        self._custom_rules: Dict[str, ScanRule] = {}

        # 添加默认模式分析器
        self.analyzers.append(PatternAnalyzer())

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
        """发现技能文件"""
        files: List[SkillFile] = []
        path = Path(skill_path)

        if not path.exists() or not path.is_dir():
            return files

        # 可扫描的文件类型
        scannable_suffixes = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".cfg",
            ".ini",
            ".sh",
            ".bat",
            ".ps1",
        }

        for file_path in sorted(path.rglob("*")):
            if not file_path.is_file():
                continue

            # 跳过隐藏目录和缓存
            rel_path = file_path.relative_to(path)
            parts = rel_path.parts
            if any(p.startswith(".") or p == "__pycache__" or p == "node_modules" for p in parts):
                continue

            # 检查文件类型
            if file_path.suffix not in scannable_suffixes:
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

        # 发现文件
        files = self._discover_files(skill_path)
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
                ],
            )

        # 计算内容哈希
        all_content = "\n".join(f.content for f in files)
        content_hash = self._compute_content_hash(all_content)

        # 检查缓存
        cached = self._cache.get(skill_id, content_hash)
        if cached:
            logger.debug("缓存命中: %s", skill_id)
            return cached

        # 执行扫描
        all_findings: List[Finding] = []

        for skill_file in files:
            for analyzer in self.analyzers:
                findings = analyzer.analyze(skill_file)
                all_findings.extend(findings)

        # 根据策略判断是否通过
        if self.policy == ScanPolicy.DENY:
            passed = not any(f.severity in ("critical", "high") for f in all_findings)
        elif self.policy == ScanPolicy.WARN:
            passed = not any(f.severity == "critical" for f in all_findings)
        else:  # ALLOW
            passed = True

        result = ScanResult(
            skill_id=skill_id,
            passed=passed,
            findings=all_findings,
            scan_mode=mode,
            content_hash=content_hash,
            scan_duration=time.time() - start_time,
            file_count=len(files),
        )

        # 缓存结果
        self._cache.set(skill_id, content_hash, result)

        logger.info("技能扫描完成: %s, 通过=%s, " f"文件数=%s, 发现=%s", skill_id, passed, len(files), len(all_findings))

        return result
