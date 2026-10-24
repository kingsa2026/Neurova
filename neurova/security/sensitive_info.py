"""内容级敏感信息的识别与脱敏——**唯一**实装（§6-411 批 O-5 收口）。

收口前有四份并存（逐份的强项与缺陷记在台账 §6-411 与判据
`tests/unit/security/test_sensitiveInfoRulesAreSingleSourced.py` 头部）。
本模块按教义第 7 条取三份的长处合成一张表，并把四套各自写一遍的脱敏循环收成一个引擎：

- 规则表 `SENSITIVE_RULES`：一条规则一个名字、一条正则、一个分级、一种打码形状。
- 识别 `detectSensitive()`；脱敏 `sanitizeSensitive()`；保留格式的匿名化 `maskPreservingFormat()`。
- 分级尺度只有一份（`SensitivityLevel`）。记忆侧 `security.py` 里那个同名枚举改成本类的**别名**，
  `cognitive_security.py` 的 `SafetyLevel` 是它自己报告用的词汇（多一档 `SAFE`），
  每条规则的分级从本表取、经 `_SEVERITY_TO_SAFETY` 投影过去——投影不是第二份定义。

`security/privacy_gate.py` 不在本表射程内：它做的是"工具事件载荷按**键名**递归脱敏"，
另一件功能、在役（`chat_pipeline.py:2522/2712`），并进来反而会把两种口径搅混。

为什么不接进回合链：本批只收口单源（用户裁）。三扇 door 今天都没有生产消费者
（`CognitiveSecuritySystem` 在 `neurova/` 内零引用，档案 M2），所以合并带来的分级上调
（身份证 HIGH→CRITICAL、手机号 MEDIUM→HIGH、邮箱 LOW→MEDIUM）当前是惰性的；
要不要按新尺度往回合里接，留给后续那一拍。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Pattern, Tuple

__all__ = [
    "SensitivityLevel",
    "SensitiveRule",
    "SENSITIVE_RULES",
    "Detection",
    "detectSensitive",
    "sanitizeSensitive",
    "maskPreservingFormat",
    "ruleByName",
    "severityOf",
    "severityRank",
    "highestSeverity",
]


class SensitivityLevel(Enum):
    """敏感度尺度（唯一一份）。取值语义沿用记忆侧原本的四级。"""

    LOW = "low"        # 一般信息
    MEDIUM = "medium"  # 可定位到个人的信息
    HIGH = "high"      # 个人信息
    CRITICAL = "critical"  # 财务／证件／可直接冒用的凭据


_MASK_KEY_VALUE = "keyValue"    # 只打码值，键名与分隔符保留（`API_KEY=***`）
_MASK_KEEP_EDGES = "keepEdges"   # 保留首若干位与末若干位（手机号、卡号、证件号）
_MASK_WHOLE = "whole"            # 整段替换（值形状：`sk-…`、`Bearer …`）


@dataclass(frozen=True)
class SensitiveRule:
    """一条敏感信息规则：名字＋正则＋分级＋打码形状。"""

    name: str
    pattern: Pattern
    severity: SensitivityLevel
    description: str
    #: 打码策略（三种之一；新形状要加策略就得先说明为什么现成的三种不够）
    maskStrategy: str = _MASK_WHOLE
    #: `keepEdges` 策略用：保留的前／后位数
    keepLeading: int = 0
    keepTrailing: int = 0
    #: 该规则匹配的是"值形状"而非"键名＋值"——裸词反例判据据此放行它（`sk-\w+` 不是裸词）
    matchesValueShapeOnly: bool = False
    #: 键值式规则里键名与值所在的分组名
    keyGroup: str = "key"
    valueGroup: str = "value"
    #: 单条规则的开关（记忆侧 `remove_pattern()` 那个扩展点要用；默认开）
    enabled: bool = True
    #: 字面替换串。给了它就整段替换成这个串——**配置里写 replacement 的人必须看得见效果**，
    #: 静默忽略就是一个新的"只写不读"（同一批在 firewall 那边修的正是这类）。
    literalReplacement: Optional[str] = None

    def maskText(self, text: str) -> str:
        if not self.enabled:
            return text
        return self._maskText(text)

    def findMatches(self, text: str) -> List[re.Match]:
        if not self.enabled:
            return []
        return list(self.pattern.finditer(text))

    def _maskText(self, text: str) -> str:
        """按本规则的形状打码一段文本（打码实现只在这里一份）。"""
        if self.literalReplacement is not None:
            return self.pattern.sub(self.literalReplacement, text)
        if self.maskStrategy == _MASK_KEY_VALUE:
            def _sub(match: re.Match) -> str:
                return "%s%s***" % (match.group(self.keyGroup), match.group("sep"))
            return self.pattern.sub(_sub, text)
        if self.maskStrategy == _MASK_KEEP_EDGES:
            def _edge(match: re.Match) -> str:
                value = match.group(0)
                head = value[:self.keepLeading]
                tail = value[-self.keepTrailing:] if self.keepTrailing else ""
                middle = "*" * max(1, len(value) - len(head) - len(tail))
                return head + middle + tail
            return self.pattern.sub(_edge, text)
        return self.pattern.sub("***", text)


def _kv(name: str, key: str, severity: SensitivityLevel, description: str,
        valueClass: str = r"\S+") -> SensitiveRule:
    """键名＋**赋值符**＋值 一形（`=`／`:`／全角冒号，两侧可有空白）。

    为什么赋值符是必需的：原记忆侧那份允许"空白也算分隔符"，于是
    "这里有一个 token 字段说明文档"这类正常散文会被当成令牌打码——把正常文本打花不是
    更安全，是制造噪声并让人开始忽略脱敏结果。原 cognitive 那份要求 `[=:]`，与现有
    格子（`test_should_remember_only_triggers_on_key_value_form`）同源，取它。
    """
    return SensitiveRule(
        name=name,
        pattern=re.compile(r"(?P<key>%s)(?P<sep>[ 	]*[=:：][ 	]*)(?P<value>%s)"
                           % (key, valueClass), re.IGNORECASE),
        severity=severity,
        description=description,
        maskStrategy=_MASK_KEY_VALUE,
    )


def _shape(name: str, pattern: str, severity: SensitivityLevel, description: str) -> SensitiveRule:
    """值形状一形：没有键名也能认出凭据长什么样（原 firewall 表独有的那块能力）。"""
    return SensitiveRule(
        name=name, pattern=re.compile(pattern), severity=severity, description=description,
        maskStrategy=_MASK_WHOLE, matchesValueShapeOnly=True,
    )


#: 合并表。分级取三份里**较高**的一档（隐私保守方向；往下调等于把既有保护改弱）。
SENSITIVE_RULES: Tuple[SensitiveRule, ...] = (
    _kv("password", r"(?:password|passwd|pwd|密码|口令)", SensitivityLevel.CRITICAL, "密码字段"),
    _kv("api_key", r"(?:api[_\s-]?key|apikey|secret[_\s-]?key|access[_\s-]?key)",
        SensitivityLevel.CRITICAL, "API 密钥"),
    _kv("token", r"(?:token|access[_\s-]?token|refresh[_\s-]?token|bearer)",
        SensitivityLevel.HIGH, "令牌"),
    _shape("secret_literal", r"sk-[A-Za-z0-9_\-]{8,}", SensitivityLevel.CRITICAL,
           "OpenAI 式密钥字面量"),
    _shape("bearer_literal", r"Bearer\s+[A-Za-z0-9._\-]{8,}", SensitivityLevel.HIGH,
           "Bearer 凭据字面量"),
    # 下面两条来自**在役**的另两处脱敏点（`context/summarizing_compressor.py:_REDACT_PATTERNS`
    # 与 `llm/providers/error_mapping.py:_KEY_PATTERN`）。把它们收进表里，是为了让那两处
    # 日后改接单源时不必再自带一张小抄——本批先合表，接线那一拍见工单。
    _shape("github_token", r"ghp_[A-Za-z0-9]{20,}", SensitivityLevel.CRITICAL,
           "GitHub personal access token"),
    _shape("neurova_key_literal", r"nvk_[A-Za-z0-9_\-]{8,}", SensitivityLevel.CRITICAL,
           "Neurova 式密钥字面量"),
    SensitiveRule(
        name="phone", pattern=re.compile(r"1[3-9]\d{9}"), severity=SensitivityLevel.HIGH,
        description="中国大陆手机号", maskStrategy=_MASK_KEEP_EDGES,
        keepLeading=3, keepTrailing=4, matchesValueShapeOnly=True,
    ),
    SensitiveRule(
        name="id_card",
        pattern=re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
                           r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
        severity=SensitivityLevel.CRITICAL, description="中国大陆身份证号",
        maskStrategy=_MASK_KEEP_EDGES, keepLeading=3, keepTrailing=4, matchesValueShapeOnly=True,
    ),
    SensitiveRule(
        # 收口前 memory 表把这条以 bank_card／credit_card 登记了两次——同一条正则只留一个名字。
        name="bank_card", pattern=re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
        severity=SensitivityLevel.CRITICAL, description="银行／信用卡卡号",
        maskStrategy=_MASK_KEEP_EDGES, keepLeading=0, keepTrailing=4, matchesValueShapeOnly=True,
    ),
    SensitiveRule(
        name="email", pattern=re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        severity=SensitivityLevel.MEDIUM, description="电子邮箱地址",
        maskStrategy=_MASK_WHOLE, matchesValueShapeOnly=True,
    ),
    SensitiveRule(
        name="ip_address", pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        severity=SensitivityLevel.LOW, description="IP 地址",
        maskStrategy=_MASK_WHOLE, matchesValueShapeOnly=True,
    ),
)

_BY_NAME = {rule.name: rule for rule in SENSITIVE_RULES}


@dataclass(frozen=True)
class Detection:
    """一次命中：规则＋原文位置＋**已打码**的证据（原文不外泄）。"""

    rule: SensitiveRule
    evidence: str
    start: int
    end: int

    @property
    def severity(self) -> SensitivityLevel:
        return self.rule.severity


def ruleByName(name: str) -> Optional[SensitiveRule]:
    return _BY_NAME.get(name)


def severityOf(name: str) -> SensitivityLevel:
    rule = _BY_NAME.get(name)
    if rule is None:
        raise KeyError("敏感信息规则表里没有这个名字：%r" % name)
    return rule.severity


def detectSensitive(text: str, rules: Optional[Iterable[SensitiveRule]] = None) -> List[Detection]:
    """按表识别内容级敏感信息。`rules` 给的是"默认表＋调用方追加的自定义规则"这一形
    （记忆侧 `import_patterns()` 那个扩展点走这里，不在别处再写一遍循环）。"""
    if not text:
        return []
    out: List[Detection] = []
    for rule in (rules if rules is not None else SENSITIVE_RULES):
        for match in rule.findMatches(text):  # findMatches 内部已跳过停用规则
            evidence = match.group(0)
            masked = rule.maskText(evidence)
            out.append(Detection(rule=rule, evidence=masked,
                                 start=match.start(), end=match.end()))
    return out


def sanitizeSensitive(text: str, rules: Optional[Iterable[SensitiveRule]] = None) -> str:
    """逐规则打码（脱敏引擎唯一一份）。"""
    if not text:
        return text
    out = text
    for rule in (rules if rules is not None else SENSITIVE_RULES):
        out = rule.maskText(out)
    return out


#: 尺度序（唯一一份）。`_RANK` 按枚举定义顺序生成，谁改了枚举顺序它就跟着变——
#: 不做字母序比较（原记忆侧那句 `max(levels, key=lambda x: x.value)` 会把 "medium" 当成比
#: "critical" 更高，因为它是按字符串比大小）。
_RANK: Tuple[SensitivityLevel, ...] = (
    SensitivityLevel.LOW, SensitivityLevel.MEDIUM, SensitivityLevel.HIGH, SensitivityLevel.CRITICAL,
)


def severityRank(level: SensitivityLevel) -> int:
    return _RANK.index(level)


def highestSeverity(detections: Iterable[Detection]) -> Optional[SensitivityLevel]:
    """命中里的最高分级；没有命中给 None（调用方自己决定"没检测到"算哪一档）。"""
    hits = [d.severity for d in detections]
    if not hits:
        return None
    return max(hits, key=severityRank)


def maskPreservingFormat(text: str, rules: Optional[Iterable[SensitiveRule]] = None) -> str:
    """保留长度的匿名化（原记忆侧 `anonymize_content(preserve_format=True)` 那一档语义）：
    首尾各留一个字符，中间按原长度打星。仍然只有一份引擎，只是打码形状不同。"""
    if not text:
        return text

    def _preserve(match: re.Match) -> str:
        original = match.group(0)
        if len(original) <= 4:
            return "*" * len(original)
        return original[0] + "*" * (len(original) - 2) + original[-1]

    out = text
    for rule in (rules if rules is not None else SENSITIVE_RULES):
        out = rule.pattern.sub(_preserve, out)
    return out
