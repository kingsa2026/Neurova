"""
Neurova 认知安全 (Cognitive Security) 2.0

提供认知层面的安全防护：
- 防 Prompt 注入
- 输出过滤
- 敏感信息检测
- 认知安全检查（利用 Neurova 认知能力）

与 Neurova 的认知增强特性深度集成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import enum
import json
import logging
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Set

logger = logging.getLogger(__name__)


class SafetyLevel(str, Enum):
    """安全等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatType(str, Enum):
    """威胁类型"""
    PROMPT_INJECTION = "prompt_injection"
    SENSITIVE_INFO_LEAK = "sensitive_info_leak"
    HARMFUL_CONTENT = "harmful_content"
    MALICIOUS_CODE = "malicious_code"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    MANIPULATION = "manipulation"


@dataclass
class ThreatFinding:
    """威胁发现"""
    threat_type: ThreatType
    severity: SafetyLevel
    description: str
    evidence: str = ""
    location: str = ""
    confidence: float = 0.0
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "threat_type": self.threat_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "evidence": self.evidence[:200] if self.evidence else "",
            "location": self.location,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SafetyCheckResult:
    """安全检查结果"""
    is_safe: bool
    safety_level: SafetyLevel
    findings: List[ThreatFinding] = field(default_factory=list)
    sanitized_text: Optional[str] = None
    check_duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_threats(self) -> bool:
        return len(self.findings) > 0

    @property
    def highest_severity(self) -> Optional[SafetyLevel]:
        if not self.findings:
            return None
        severity_order = {
            SafetyLevel.LOW: 0,
            SafetyLevel.MEDIUM: 1,
            SafetyLevel.HIGH: 2,
            SafetyLevel.CRITICAL: 3,
        }
        return max(self.findings, key=lambda f: severity_order.get(f.severity, 0)).severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "safety_level": self.safety_level.value,
            "findings": [f.to_dict() for f in self.findings],
            "sanitized_text": self.sanitized_text,
            "check_duration_ms": self.check_duration_ms,
            "metadata": self.metadata,
        }


class PromptInjectionDetector:
    """Prompt 注入检测器"""

    # 常见的 Prompt 注入模式
    INJECTION_PATTERNS = [
        # 直接指令覆盖
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'disregard\s+(all\s+)?prior\s+instructions',
        r'forget\s+(all\s+)?previous\s+instructions',
        r'override\s+(all\s+)?previous\s+instructions',

        # 角色切换
        r'you\s+are\s+now\s+',
        r'act\s+as\s+',
        r'pretend\s+to\s+be\s+',
        r'roleplay\s+as\s+',
        r'impersonate\s+',

        # 系统提示泄露
        r'show\s+me\s+(your|the)\s+(system|initial)\s+(prompt|instructions)',
        r'what\s+(is|are)\s+your\s+(system|initial)\s+(prompt|instructions)',
        r'reveal\s+(your|the)\s+(system|initial)\s+(prompt|instructions)',
        r'print\s+(your|the)\s+(system|initial)\s+(prompt|instructions)',

        # 编码/混淆攻击
        r'base64\s+decode',
        r'rot13\s+',
        r'\\x[0-9a-fA-F]{2}',
        r'\\u[0-9a-fA-F]{4}',

        # 分隔符注入
        r'---\s*END\s+OF\s+(SYSTEM|INSTRUCTIONS)',
        r'---\s*START\s+OF\s+(NEW|USER)\s+(INSTRUCTIONS|PROMPT)',
        r'<\|im_start\|>',
        r'<\|im_end\|>',
        r'<\|system\|>',
        r'<\|user\|>',

        # 中文注入模式
        r'忽略.{0,10}(指令|规则|限制)',
        r'无视.{0,10}(指令|规则|限制)',
        r'忘记.{0,10}(指令|规则|限制)',
        r'你现在是',
        r'假装(你是|成为|自己是)',
        r'显示.{0,10}(提示词|指令|规则)',
        r'告诉我.{0,10}(提示词|指令|规则)',
    ]

    def __init__(self, custom_patterns: Optional[List[str]] = None):
        self._patterns: List[Pattern] = []

        # 加载默认模式
        for pattern in self.INJECTION_PATTERNS:
            try:
                self._patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                logger.warning(f"编译正则失败: {pattern}")

        # 加载自定义模式
        if custom_patterns:
            for pattern in custom_patterns:
                try:
                    self._patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning(f"编译自定义正则失败: {pattern}")

    def detect(self, text: str) -> List[ThreatFinding]:
        """检测 Prompt 注入"""
        if not text:
            return []

        findings = []

        for pattern in self._patterns:
            match = pattern.search(text)
            if match:
                findings.append(ThreatFinding(
                    threat_type=ThreatType.PROMPT_INJECTION,
                    severity=SafetyLevel.HIGH,
                    description=f"检测到潜在的 Prompt 注入",
                    evidence=match.group(),
                    location=f"位置 {match.start()}-{match.end()}",
                    confidence=0.8,
                ))

        return findings

    def add_pattern(self, pattern: str):
        """添加自定义检测模式"""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            self._patterns.append(compiled)
        except re.error as e:
            logger.error(f"添加模式失败: {e}")


class SensitiveInfoDetector:
    """敏感信息检测器"""

    # 敏感信息模式
    SENSITIVE_PATTERNS = {
        "phone": (r'1[3-9]\d{9}', SafetyLevel.MEDIUM),
        "email": (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', SafetyLevel.LOW),
        "id_card": (r'\d{17}[\dXx]', SafetyLevel.HIGH),
        "bank_card": (r'\d{16,19}', SafetyLevel.HIGH),
        "password": (r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+', SafetyLevel.HIGH),
        "api_key": (r'(?i)(api[_\s-]?key|apikey|secret[_\s-]?key)\s*[=:]\s*\S+', SafetyLevel.CRITICAL),
        "token": (r'(?i)(token|access[_\s-]?token|bearer)\s*[=:]\s*\S+', SafetyLevel.HIGH),
        "ip_address": (r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', SafetyLevel.LOW),
    }

    def __init__(self, custom_patterns: Optional[Dict[str, tuple]] = None):
        self._patterns: Dict[str, tuple] = {}

        # 加载默认模式
        for name, (pattern, severity) in self.SENSITIVE_PATTERNS.items():
            try:
                self._patterns[name] = (re.compile(pattern, re.IGNORECASE), severity)
            except re.error:
                logger.warning(f"编译正则失败: {pattern}")

        # 加载自定义模式
        if custom_patterns:
            for name, (pattern, severity) in custom_patterns.items():
                try:
                    self._patterns[name] = (re.compile(pattern, re.IGNORECASE), severity)
                except re.error:
                    logger.warning(f"编译自定义正则失败: {pattern}")

    def detect(self, text: str) -> List[ThreatFinding]:
        """检测敏感信息"""
        if not text:
            return []

        findings = []

        for info_type, (pattern, severity) in self._patterns.items():
            matches = pattern.finditer(text)
            for match in matches:
                # 掩码显示
                matched_text = match.group()
                if len(matched_text) > 6:
                    masked = matched_text[:3] + "***" + matched_text[-3:]
                else:
                    masked = "***"

                findings.append(ThreatFinding(
                    threat_type=ThreatType.SENSITIVE_INFO_LEAK,
                    severity=severity,
                    description=f"检测到敏感信息: {info_type}",
                    evidence=masked,
                    location=f"位置 {match.start()}-{match.end()}",
                    confidence=0.9,
                ))

        return findings

    def sanitize(self, text: str) -> str:
        """清理敏感信息"""
        if not text:
            return text

        result = text

        for info_type, (pattern, _) in self._patterns.items():
            if info_type == "phone":
                result = pattern.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], result)
            elif info_type == "email":
                result = pattern.sub(lambda m: "***@***.***", result)
            elif info_type == "id_card":
                result = pattern.sub(lambda m: m.group()[:3] + "***********" + m.group()[-4:], result)
            elif info_type == "bank_card":
                result = pattern.sub(lambda m: "****" + m.group()[-4:], result)
            elif info_type in ("password", "api_key", "token"):
                result = pattern.sub(lambda m: m.group().split("=")[0] + "=***", result)
            else:
                result = pattern.sub("***", result)

        return result


class OutputFilter:
    """输出过滤器"""

    # 不当内容模式
    HARMFUL_PATTERNS = [
        # 暴力内容
        r'(?i)how\s+to\s+make.{0,20}(bomb|explosive|weapon)',
        r'(?i)(kill|murder|assassinate)\s+(someone|people|person)',

        # 自我伤害
        r'(?i)(how\s+to|ways\s+to)\s+(harm|hurt|kill)\s+(my)?self',

        # 非法活动
        r'(?i)(how\s+to|instructions?\s+for)\s+(hack|crack|break\s+into)',
        r'(?i)(how\s+to|instructions?\s+for)\s+(steal|shoplift|pickpocket)',

        # 中文有害内容
        r'怎么.{0,5}(制作|制造|做).{0,5}(炸弹|爆炸物|武器)',
        r'怎么.{0,5}(黑入|入侵|破解)',
    ]

    def __init__(self, custom_patterns: Optional[List[str]] = None):
        self._patterns: List[Pattern] = []

        # 加载默认模式
        for pattern in self.HARMFUL_PATTERNS:
            try:
                self._patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                logger.warning(f"编译正则失败: {pattern}")

        # 加载自定义模式
        if custom_patterns:
            for pattern in custom_patterns:
                try:
                    self._patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning(f"编译自定义正则失败: {pattern}")

    def filter(self, text: str) -> tuple[str, List[ThreatFinding]]:
        """过滤不当内容"""
        if not text:
            return text, []

        findings = []
        filtered_text = text

        for pattern in self._patterns:
            match = pattern.search(filtered_text)
            if match:
                findings.append(ThreatFinding(
                    threat_type=ThreatType.HARMFUL_CONTENT,
                    severity=SafetyLevel.CRITICAL,
                    description="检测到不当内容",
                    evidence=match.group()[:50],
                    location=f"位置 {match.start()}-{match.end()}",
                    confidence=0.9,
                ))
                # 替换为 [内容已过滤]
                filtered_text = pattern.sub("[内容已过滤]", filtered_text)

        return filtered_text, findings


class CognitiveSafetyChecker:
    """认知安全检查器"""

    def __init__(self, safety_level: SafetyLevel = SafetyLevel.MEDIUM):
        self._safety_level = safety_level
        self._risk_thresholds = {
            SafetyLevel.LOW: 0.5,
            SafetyLevel.MEDIUM: 0.3,
            SafetyLevel.HIGH: 0.2,
            SafetyLevel.CRITICAL: 0.1,
        }

    def check_intent_safety(self, intent: str, context: Optional[Dict[str, Any]] = None) -> SafetyCheckResult:
        """检查意图安全性"""
        start_time = time.time()

        if not intent:
            return SafetyCheckResult(
                is_safe=True,
                safety_level=SafetyLevel.LOW,
                check_duration_ms=(time.time() - start_time) * 1000,
            )

        findings = []
        risk_score = 0.0

        # 危险关键词检测
        dangerous_keywords = [
            "rm -rf", "sudo", "chmod 777", "DROP TABLE", "DELETE FROM",
            "eval(", "exec(", "__import__", "subprocess",
        ]

        for keyword in dangerous_keywords:
            if keyword.lower() in intent.lower():
                risk_score += 0.3
                findings.append(ThreatFinding(
                    threat_type=ThreatType.MALICIOUS_CODE,
                    severity=SafetyLevel.HIGH,
                    description=f"意图包含危险关键词: {keyword}",
                    evidence=keyword,
                    confidence=0.8,
                ))

        # 认知安全评估
        cognitive_assessment = self._cognitive_safety_assessment(intent, context)
        risk_score += cognitive_assessment.get("risk_score", 0.0)
        findings.extend(cognitive_assessment.get("findings", []))

        # 确定安全等级
        threshold = self._risk_thresholds.get(self._safety_level, 0.7)
        is_safe = risk_score < threshold

        if risk_score >= 0.8:
            safety_level = SafetyLevel.CRITICAL
        elif risk_score >= 0.5:
            safety_level = SafetyLevel.HIGH
        elif risk_score >= 0.3:
            safety_level = SafetyLevel.MEDIUM
        else:
            safety_level = SafetyLevel.LOW

        return SafetyCheckResult(
            is_safe=is_safe,
            safety_level=safety_level,
            findings=findings,
            check_duration_ms=(time.time() - start_time) * 1000,
            metadata={"risk_score": risk_score},
        )

    def _cognitive_safety_assessment(self, intent: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """认知安全评估"""
        findings = []
        risk_score = 0.0

        # 检查是否试图绕过安全限制
        bypass_patterns = [
            r'(?i)ignore\s+(all\s+)?(safety|security)',
            r'(?i)bypass\s+(all\s+)?(safety|security)',
            r'(?i)disable\s+(all\s+)?(safety|security)',
        ]

        for pattern in bypass_patterns:
            if re.search(pattern, intent):
                risk_score += 0.5
                findings.append(ThreatFinding(
                    threat_type=ThreatType.PRIVILEGE_ESCALATION,
                    severity=SafetyLevel.HIGH,
                    description="检测到绕过安全限制的尝试",
                    confidence=0.7,
                ))

        return {
            "risk_score": risk_score,
            "findings": findings,
        }

    def monitor_execution_safety(self, command: str, output: str) -> SafetyCheckResult:
        """监控执行安全性"""
        start_time = time.time()
        findings = []

        # 检查输出中是否包含敏感信息
        sensitive_detector = SensitiveInfoDetector()
        sensitive_findings = sensitive_detector.detect(output)
        findings.extend(sensitive_findings)

        # 检查是否有异常输出
        if len(output) > 100000:  # 输出过大
            findings.append(ThreatFinding(
                threat_type=ThreatType.DATA_EXFILTRATION,
                severity=SafetyLevel.MEDIUM,
                description="输出数据量异常大",
                evidence=f"输出大小: {len(output)} 字符",
                confidence=0.6,
            ))

        is_safe = len(findings) == 0
        safety_level = SafetyLevel.LOW if is_safe else SafetyLevel.MEDIUM

        return SafetyCheckResult(
            is_safe=is_safe,
            safety_level=safety_level,
            findings=findings,
            check_duration_ms=(time.time() - start_time) * 1000,
        )


class MemorySecurityGuard:
    """记忆安全守卫"""

    # 不应被记住的敏感信息类型
    SENSITIVE_MEMORY_TYPES = {
        "password", "api_key", "token", "secret",
        "credit_card", "bank_account", "id_card",
    }

    def __init__(self):
        self._sensitive_detector = SensitiveInfoDetector()

    def sanitize_memory(self, memory_content: str) -> str:
        """清理记忆内容"""
        if not memory_content:
            return memory_content

        # 检测并清理敏感信息
        return self._sensitive_detector.sanitize(memory_content)

    def should_remember(self, content: str, memory_type: str = "general") -> bool:
        """判断是否应该记住该内容"""
        # 检查记忆类型
        if memory_type in self.SENSITIVE_MEMORY_TYPES:
            logger.warning(f"不应记住敏感类型的记忆: {memory_type}")
            return False

        # 检查内容中是否包含敏感信息
        findings = self._sensitive_detector.detect(content)
        if findings:
            # 如果包含高敏感度信息，不应记住
            high_severity = [f for f in findings if f.severity in (SafetyLevel.HIGH, SafetyLevel.CRITICAL)]
            if high_severity:
                logger.warning("内容包含高敏感度信息，不应记住")
                return False

        return True

    def check_memory_safety(self, memory_content: str) -> SafetyCheckResult:
        """检查记忆安全性"""
        start_time = time.time()
        findings = []

        # 检测敏感信息
        sensitive_findings = self._sensitive_detector.detect(memory_content)
        findings.extend(sensitive_findings)

        # 确定安全等级
        if not findings:
            safety_level = SafetyLevel.LOW
        elif any(f.severity == SafetyLevel.CRITICAL for f in findings):
            safety_level = SafetyLevel.CRITICAL
        elif any(f.severity == SafetyLevel.HIGH for f in findings):
            safety_level = SafetyLevel.HIGH
        else:
            safety_level = SafetyLevel.MEDIUM

        return SafetyCheckResult(
            is_safe=len(findings) == 0,
            safety_level=safety_level,
            findings=findings,
            sanitized_text=self.sanitize_memory(memory_content) if findings else None,
            check_duration_ms=(time.time() - start_time) * 1000,
        )


class CognitiveSecuritySystem:
    """认知安全系统"""

    def __init__(self, safety_level: SafetyLevel = SafetyLevel.MEDIUM):
        self._safety_level = safety_level

        # 初始化各组件
        self._prompt_detector = PromptInjectionDetector()
        self._sensitive_detector = SensitiveInfoDetector()
        self._output_filter = OutputFilter()
        self._safety_checker = CognitiveSafetyChecker(safety_level)
        self._memory_guard = MemorySecurityGuard()

        logger.info(f"认知安全系统初始化完成，安全等级: {safety_level.value}")

    def check_input_safety(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> SafetyCheckResult:
        """检查输入安全性"""
        start_time = time.time()
        all_findings = []

        # 1. Prompt 注入检测
        injection_findings = self._prompt_detector.detect(user_input)
        all_findings.extend(injection_findings)

        # 2. 敏感信息检测
        sensitive_findings = self._sensitive_detector.detect(user_input)
        all_findings.extend(sensitive_findings)

        # 3. 意图安全检查
        intent_result = self._safety_checker.check_intent_safety(user_input, context)
        all_findings.extend(intent_result.findings)

        # 确定整体安全性
        is_safe = len(all_findings) == 0
        if not all_findings:
            safety_level = SafetyLevel.LOW
        elif any(f.severity == SafetyLevel.CRITICAL for f in all_findings):
            safety_level = SafetyLevel.CRITICAL
        elif any(f.severity == SafetyLevel.HIGH for f in all_findings):
            safety_level = SafetyLevel.HIGH
        else:
            safety_level = SafetyLevel.MEDIUM

        return SafetyCheckResult(
            is_safe=is_safe,
            safety_level=safety_level,
            findings=all_findings,
            check_duration_ms=(time.time() - start_time) * 1000,
        )

    def check_output_safety(self, output: str) -> SafetyCheckResult:
        """检查输出安全性"""
        start_time = time.time()
        all_findings = []

        # 1. 敏感信息检测
        sensitive_findings = self._sensitive_detector.detect(output)
        all_findings.extend(sensitive_findings)

        # 2. 不当内容过滤
        filtered_output, harmful_findings = self._output_filter.filter(output)
        all_findings.extend(harmful_findings)

        # 确定整体安全性
        is_safe = len(all_findings) == 0
        if not all_findings:
            safety_level = SafetyLevel.LOW
        elif any(f.severity == SafetyLevel.CRITICAL for f in all_findings):
            safety_level = SafetyLevel.CRITICAL
        elif any(f.severity == SafetyLevel.HIGH for f in all_findings):
            safety_level = SafetyLevel.HIGH
        else:
            safety_level = SafetyLevel.MEDIUM

        return SafetyCheckResult(
            is_safe=is_safe,
            safety_level=safety_level,
            findings=all_findings,
            sanitized_text=filtered_output if harmful_findings else None,
            check_duration_ms=(time.time() - start_time) * 1000,
        )

    def sanitize_memory(self, memory_content: str) -> str:
        """清理记忆内容"""
        return self._memory_guard.sanitize_memory(memory_content)

    def check_memory_safety(self, memory_content: str) -> SafetyCheckResult:
        """检查记忆安全性"""
        return self._memory_guard.check_memory_safety(memory_content)

    def monitor_execution(self, command: str, output: str) -> SafetyCheckResult:
        """监控执行安全性"""
        return self._safety_checker.monitor_execution_safety(command, output)

    def detect_prompt_injection(self, text: str) -> List[ThreatFinding]:
        """检测 Prompt 注入"""
        return self._prompt_detector.detect(text)

    def detect_sensitive_info(self, text: str) -> List[ThreatFinding]:
        """检测敏感信息"""
        return self._sensitive_detector.detect(text)
