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
    "containsSensitive",
    "isCredentialKey",
    "MIN_SECRET_VALUE_LEN",
    "sanitizeSensitive",
    "maskPreservingFormat",
    "ruleByName",
    "severityOf",
    "severityRank",
    "highestSeverity",
    "SUMMARY_RULES",
    "ERROR_TEXT_RULES",
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
    #: 键名档的正则**原文**（只有键值式规则带）。结构侧问"这个键是不是凭据"就按它判——
    #: 派生自同一张表，不在调用方再抄一份键名表（§6-415 批 P-5：证据写入口拿的是 dict，
    #: 内容形状的正则看不见"键在结构里、值在另一个字符串里"这一形）。
    keyPattern: Optional[str] = None

    def maskText(self, text: str, token: str = "***") -> str:
        if not self.enabled:
            return text
        return self._maskText(text, token)

    def findMatches(self, text: str) -> List[re.Match]:
        if not self.enabled:
            return []
        return list(self.pattern.finditer(text))

    def _maskText(self, text: str, token: str = "***") -> str:
        """按本规则的形状打码一段文本（打码实现只在这里一份）。

        `token` 是**出口词汇**，不是第二种形状：键值式仍保键名、值形状仍整段替换。
        三处在役侧（摘要／错误文案／进化证据）今天各用 `[REDACTED]` 家族，且已有格子钉着
        （`test_summarizing_compressor.py:89`、`test_evolution_gates_wave_c.py:83`），
        而存量证据文本里也是那串——统一成 `***` 会让新旧文本混排，故按调用方给词汇。
        `keepEdges` 那一档不吃 token：它靠"留首末几位＋中间补星"保长度，换成文字就废了。
        """
        if self.literalReplacement is not None:
            return self.pattern.sub(self.literalReplacement.replace("***", token), text)
        if self.maskStrategy == _MASK_KEY_VALUE:
            def _sub(match: re.Match) -> str:
                return "%s%s%s" % (match.group(self.keyGroup), match.group("sep"), token)
            return self.pattern.sub(_sub, text)
        if self.maskStrategy == _MASK_KEEP_EDGES:
            def _edge(match: re.Match) -> str:
                value = match.group(0)
                head = value[:self.keepLeading]
                tail = value[-self.keepTrailing:] if self.keepTrailing else ""
                middle = "*" * max(1, len(value) - len(head) - len(tail))
                return head + middle + tail
            return self.pattern.sub(_edge, text)
        return self.pattern.sub(token, text)


def _kv(name: str, key: str, severity: SensitivityLevel,
        description: str) -> SensitiveRule:
    r"""键名＋**赋值符**＋值 一形（`=`／`:`／全角冒号，两侧可有空白，键名右引号可选）。

    为什么赋值符是必需的：原记忆侧那份允许"空白也算分隔符"，于是
    "这里有一个 token 字段说明文档"这类正常散文会被当成令牌打码——把正常文本打花不是
    更安全，是制造噪声并让人开始忽略脱敏结果。原 cognitive 那份要求 `[=:]`，与现有
    格子（`test_should_remember_only_triggers_on_key_value_form`）同源，取它。

    键名右侧那个可选引号（`["']?`）是给 **JSON 形**留的：`{"api_key": "x"}` 里键名与
    冒号之间隔着一个闭引号，不接受它则整条 JSON 配置**一个字都不脱**（§6-415 实测）。
    值档三条分支按"先引号、后贪婪"排：引号段可以含空格（`password="Alpha7 Bravo9"` 在
    在役护栏上今天只脱到空格前，`Bravo9` 原样进证据），贪婪段 `\S+` 保持"一路吃到空白"，
    所以带逗号／分号的值不会被切成残渣留在原文里。两条分支都不设长度下限——下限属于
    **判定**（`MIN_SECRET_VALUE_LEN`），写进正则就会把脱敏面一起收窄。
    """
    return SensitiveRule(
        name=name,
        pattern=re.compile(r"(?P<key>%s)(?P<sep>[\"']?[ 	]*[=:：][ 	]*)(?P<value>"
                           r"\"[^\"]*\"|\'[^\']*\'|\S+)" % key, re.IGNORECASE),
        severity=severity,
        description=description,
        maskStrategy=_MASK_KEY_VALUE,
        keyPattern=key,
    )


def _shape(name: str, pattern: str, severity: SensitivityLevel, description: str) -> SensitiveRule:
    """值形状一形：没有键名也能认出凭据长什么样（原 firewall 表独有的那块能力）。"""
    return SensitiveRule(
        name=name, pattern=re.compile(pattern), severity=severity, description=description,
        maskStrategy=_MASK_WHOLE, matchesValueShapeOnly=True,
    )


#: 合并表。**表序＝打码序**，其中一条次序是硬约束：`bearer_literal` 必须排在键值档**之前**。
#: 理由是键值档的值类一路吃到空白，`token: Bearer abcdef123456` 若先走键值档，被吃掉的"值"
#: 只是 `Bearer` 这个词，真令牌 `abcdef123456` 原样留在原文里，而 `bearer_literal` 事后
#: 再也看不到那个前缀——这条漏形在在役的摘要出口上实测存在（§6-415 本格第一段读数），
#: 而它正是进化护栏那张表注释里写明的"Bearer 先行"理由；合表时把顺序丢了，漏点就回来了。
#: 分级取三份里**较高**的一档（隐私保守方向；往下调等于把既有保护改弱）。
SENSITIVE_RULES: Tuple[SensitiveRule, ...] = (
    # 值形状先行（Bearer 必须早于键值，理由见上）；`github_token`／`neurova_key_literal`
    # 两条来自在役的另两处脱敏点（`context/summarizing_compressor.py` 与
    # `llm/providers/error_mapping.py` 的自带表），收进表里就是为了让那两处不必再留小抄。
    _shape("bearer_literal", r"Bearer\s+\S+", SensitivityLevel.HIGH,
           "Bearer 凭据字面量"),   # 值类与在役侧（error_mapping / evolution guard）对齐：
                                   # 收窄成字符类会漏掉 `Bearer ab$` 这种值——脱敏面宁可宽
    _shape("secret_literal", r"sk-[A-Za-z0-9_\-]{8,}", SensitivityLevel.CRITICAL,
           "OpenAI 式密钥字面量"),
    _shape("github_token", r"ghp_[A-Za-z0-9]{20,}", SensitivityLevel.CRITICAL,
           "GitHub personal access token"),
    _shape("neurova_key_literal", r"nvk_[A-Za-z0-9_\-]{8,}", SensitivityLevel.CRITICAL,
           "Neurova 式密钥字面量"),
    # 键值档：键表并进化护栏那张表之长（`authorization`/`cookie`/`credential` 与裸 `secret`
    # 此前只在那一侧有，摘要出口整条放过——§6-415 实测三形均"一个字都不脱"）
    _kv("password", r"(?:password|passwd|pwd|密码|口令)", SensitivityLevel.CRITICAL, "密码字段"),
    _kv("api_key", r"(?:api[_\s-]?key|apikey|secret[_\s-]?key|access[_\s-]?key|secret)",
        SensitivityLevel.CRITICAL, "API 密钥"),
    _kv("token", r"(?:token|access[_\s-]?token|refresh[_\s-]?token|bearer|authorization"
                 r"|credential|cookie)",
        SensitivityLevel.HIGH, "令牌／会话凭据"),
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

#: 具名投影：在役出口各取一类，**名单在这里声明**，不在调用方另存小抄（§6-413 批 P-5）。
#: 为什么允许投影而不算第二份表：规则本体（正则／分级／形状）只有一份，投影只挑"这条链上
#: 该看的类别"；新增一条规则只改 `SENSITIVE_RULES`，投影按名字引用。
#: 投影**沿用表序**（`_pick` 按表过滤），所以"Bearer 先于键值"这条次序约束自动带进每一扇 door。
_SECRET_SHAPES = ("secret_literal", "neurova_key_literal", "github_token", "bearer_literal")
_CREDENTIAL_KV = ("password", "api_key", "token")


def _pick(names: Tuple[str, ...]) -> Tuple[SensitiveRule, ...]:
    missing = [n for n in names if n not in {r.name for r in SENSITIVE_RULES}]
    if missing:  # 投影引用了不存在的规则＝悄悄漏脱敏，响亮失败
        raise KeyError("单源规则表里缺这些名字，投影不成立：%s" % missing)
    return tuple(r for r in SENSITIVE_RULES if r.name in names)


#: 凭据类投影：密钥形状＋凭据键值，**不含 PII**。
#: 两个消费者共用这一个对象——摘要出口（`context/summarizing_compressor.py`）与
#: 进化输入护栏（`skills/evolution_inputs_guard.py`，§6-415 接上）。名字里的"SUMMARY"
#: 是第一条链留下的，不再另起一名造第二个投影对象；要加第三条链就照这个名单加，
#: 不要在调用方 `list(SUMMARY_RULES) + [...]`（那才是第二份表）。
SUMMARY_RULES = _pick(_SECRET_SHAPES + _CREDENTIAL_KV)
#: 错误文案：只有值形状（文案里出现手机号是正常的运维信息，不是凭据）
ERROR_TEXT_RULES = _pick(_SECRET_SHAPES)

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


#: **判定**侧的值长下限（唯一一处）。它只管"这条算不算凭据"，不管"这段要不要打码"：
#: 脱敏（`sanitizeSensitive`）不设下限，宁可多打；而 `skill_install_gate.py:211` 是
#: 命中即 fail-closed 拦下整个技能安装的门禁，`token=a` 一旦算命中，正常技能就被误杀。
#: 进化护栏那张表原先把 `{6,}` 写死在正则里（同时管住脱敏与判定两件事），合表时把下限
#: 摘出来具名放在这里——下限留在正则里，脱敏面就跟着窄了一截。
MIN_SECRET_VALUE_LEN = 6


def _valueSpan(rule: SensitiveRule, match: "re.Match") -> str:
    """一次命中里"值"那一段：键值式取 `value` 组并剥掉两侧引号，值形状取整段。"""
    if "value" in rule.pattern.groupindex:
        raw = match.group("value") or ""
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("\"", "'"):
            return raw[1:-1]
        return raw
    return match.group(0)


def detectSensitive(text: str, rules: Optional[Iterable[SensitiveRule]] = None,
                    minValueLen: int = 0) -> List[Detection]:
    """按表识别内容级敏感信息。`rules` 给的是"默认表＋调用方追加的自定义规则"这一形
    （记忆侧 `import_patterns()` 那个扩展点走这里，不在别处再写一遍循环）。

    `minValueLen` 默认 0＝识别与脱敏一样"宁多勿漏"；fail-closed 门禁走
    `containsSensitive()`，它把默认值换成 `MIN_SECRET_VALUE_LEN`。
    """
    if not text:
        return []
    out: List[Detection] = []
    for rule in (rules if rules is not None else SENSITIVE_RULES):
        for match in rule.findMatches(text):  # findMatches 内部已跳过停用规则
            if len(_valueSpan(rule, match)) < minValueLen:
                continue
            evidence = match.group(0)
            masked = rule.maskText(evidence)
            out.append(Detection(rule=rule, evidence=masked,
                                 start=match.start(), end=match.end()))
    return out


def containsSensitive(text: str, rules: Optional[Iterable[SensitiveRule]] = None,
                      minValueLen: int = MIN_SECRET_VALUE_LEN) -> bool:
    """文本里是否**还有**未脱敏的凭据形状（fail-closed 门禁的唯一判据口）。

    与脱敏走同一张表、同一批规则对象，只是不进打码循环——所以"该拦的"与"该脱的"
    不可能给出两个答案，两边的差别只有那一条具名下限。
    """
    return bool(detectSensitive(text, rules, minValueLen))


#: 键名档的正则（**从表里派生**，不是另抄一份）：只有带 `keyPattern` 的规则参与。
def _keyShapePatterns(rules: Iterable[SensitiveRule]) -> List[Pattern]:
    return [re.compile(r"(?:%s)\Z" % rule.keyPattern, re.IGNORECASE)
            for rule in rules if rule.keyPattern]


_KEY_SHAPE_PATTERNS: Tuple[Pattern, ...] = tuple(_keyShapePatterns(SENSITIVE_RULES))


def isCredentialKey(name: object, rules: Optional[Iterable[SensitiveRule]] = None) -> bool:
    r"""一个**结构里的键名**是不是凭据键（`{"api_key": …}` 那一形）。

    为什么需要它：内容形状的正则要吃"键名＋赋值符＋值"连成一串的文本，而证据／工具载荷
    常常已经是 dict——键与值分家，`redact_secrets(str(value))` 对着 `"MyRealSecret123"`
    这种**孤立值**一个字都不会脱（§6-415 活体读数）。
    用整名匹配（`\Z`）不用 `search`：`token_count`、`password_hash_policy` 这类计数字段
    不该被顺手糊掉——把正常字段打花会让读证据的人开始忽略脱敏（与 `_kv` 拒绝"空白算分隔符"
    同一个理由）。
    """
    if not isinstance(name, str) or not name.strip():
        return False
    patterns = _KEY_SHAPE_PATTERNS if rules is None else _keyShapePatterns(list(rules))
    return any(pattern.match(name.strip()) for pattern in patterns)


def sanitizeSensitive(text: str, rules: Optional[Iterable[SensitiveRule]] = None,
                      token: str = "***") -> str:
    """逐规则打码（脱敏引擎唯一一份）。`token` 只换出口词汇，不换形状。"""
    if not text:
        return text
    out = text
    for rule in (rules if rules is not None else SENSITIVE_RULES):
        out = rule.maskText(out, token)
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
