# -*- coding: utf-8 -*-
"""进化输入护栏。

进化闭环（反射式文本改进/失败分析/审批 UI）历史上把会话原文与技能 IO 摘要
直喂 LLM——密钥随文本外流的面。本模块在**写入侧**（record_usage）根治：
落库前脱敏 + 字符预算；所有下游消费方天然拿到干净文本。

**规则表与打码引擎都不在这里**（教义第 6 条）：本模块过去自写一份键表与三条
`re.compile`（键名表／值类／`Bearer 先行`的顺序理由都在那份小抄里），与
`neurova/security/sensitive_info.py` 那张表各朝一个方向漏——它缺全角冒号与引号值里的
空格，单源缺 `authorization|cookie|credential` 与 JSON 形（§6-415 两半都实测过）。
现在两个入口都是单源的一个薄封装，出口词汇沿用摘要那条链的 `[REDACTED]`：
`[REDACTED_KEY]` 那个第二词汇全仓只在这份小抄里出现过一次，没有任何逻辑把它当哨兵，
留着的代价是让"同一条链两种标记"长期存在。

- 值长下限（`contains_secret` 用）取单源的 `MIN_SECRET_VALUE_LEN`，不在此处写 `{6,}`；
- 投影 `SUMMARY_RULES` 不含手机号／邮箱／IP 那类 PII，与摘要门同一份名单。
"""
from __future__ import annotations

from typing import Any

from neurova.security.sensitive_info import (
    SUMMARY_RULES,
    containsSensitive,
    isCredentialKey,
    sanitizeSensitive,
)

__all__ = ["redact_secrets", "redact_structure", "contains_secret", "bound_text"]

_EVOLUTION_INPUT_BUDGET = 2000  # 单字段字符预算
_REDACT_TOKEN = "[REDACTED]"    # 与摘要门同一个词汇（§6-413 裁"出口词汇按调用方给"）


def redact_secrets(text: Any) -> Any:
    """密钥形态脱敏（保留键名，替换值）。非字符串输入原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    return sanitizeSensitive(text, SUMMARY_RULES, _REDACT_TOKEN)


def redact_structure(value: Any) -> Any:
    """**序列化之前**把结构脱干净（活体自证抓出来的那条根，§6-415）。

    证据摘要链今天先 `json.dumps` 再对整串文本跑正则，两个方向都漏：

    ① 嵌套字符串的引号序列化后变成 `\\"`，值档不论怎么走都只能吃到第一个空白——
       `{"note": "password=\\"Alpha7 Bravo9\\""}` 出口里 `Bravo9` 原样躺着；
    ② 键与值分家：`{"api_key": "MyRealSecret123"}` 里值是一个**孤立字符串**，
       内容形状的正则看不见"键名＋赋值符"，`redact_secrets("MyRealSecret123")`
       返回原串（实测）。只在下游文本上再猜一次引号位置，就是教义第 1 条禁的那种修法；
       正解是让结构在变成文本之前就是干净的。

    规则：`dict` 的键名过单源的 `isCredentialKey()`（**派生自同一张表**，不另抄键名表），
    命中即整值换成出口词汇；未命中则递归。`list`/`tuple` 递归；`str` 叶子过 `redact_secrets`；
    数字／布尔／None 原样（不成凭据形状）；**其它对象**折成 `redact_secrets(repr(obj))`——
    宁可把陌生对象的表示变宽一档，也不留"`default=str` 把 repr 原样写进证据"的旁路。
    """
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: (_REDACT_TOKEN if isCredentialKey(key) else redact_structure(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_structure(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_secrets(repr(value))


def contains_secret(text: Any) -> bool:
    """是否存在未脱敏的密钥形态（提交/上传门禁的 fail-closed 判据）。"""
    if not isinstance(text, str) or not text:
        return False
    return containsSensitive(text, SUMMARY_RULES)


def bound_text(text: str, max_chars: int = _EVOLUTION_INPUT_BUDGET) -> str:
    """字符预算截断（防超长 IO 摘要灌爆进化分析上下文）。"""
    if not isinstance(text, str):
        return text
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "…[truncated]"
