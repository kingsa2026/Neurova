# -*- coding: utf-8 -*-
r"""在役脱敏两扇门改接单源后的逐字相等判据（§6-413 批 P-5）。

用户裁：这两处在役点改接 `neurova/security/sensitive_info.py` 引擎，
**出口 token 保持 `[REDACTED]` 不换**，规则子集以单源里的具名投影声明
（`SUMMARY_RULES`／`ERROR_TEXT_RULES`），不在调用方存小抄。

本档只加两格——一扇门一格——断言"改接后与改接前**在役行为逐字相等**"：
把两扇门今天用到的旧正则原样抄一份当期望值（摘要侧 5 条、错误文案侧 1 条 alternation），
对若干输入比较 `旧实现结果 == 新实现结果`。

## 为什么输入按门分派，而不是每个输入两条链都断言相等（如实写，不藏）

旧两扇门各自**只脱它那一小撮**，改接单源后投影覆盖面略有出入，逐字相等只在
"旧门本就正确脱敏"的输入上成立：

- 旧摘要门对**独立** `sk-/nvk_/Bearer/ghp` 要么不脱、要么只追加 `[REDACTED]` 而漏出原值
  （见其 `sub(r"\1[REDACTED]")` 语义），新门按值形状整段替换——这类"改进"不是逐字相等，
  故独立凭据形状归到**错误文案门**那条链上去验相等（旧错误门本就整段替换 sk/nvk/Bearer）；
- 旧错误门 `_KEY_PATTERN` **不含 `ghp_`**，故 `ghp_` 只走**摘要门**（且写成 `api_key=ghp_…`
  的键值式，让旧门的键值档先把它糊平，才谈得上逐字相等）；
- 键值式 `api_key=/password=`、不含凭据的中文运维文本、**含手机号但不含凭据**的文本，
  两扇门都逐字相等——手机号那条正是"投影用错就会当场红"的钉子。

## 钉子的形状

- 结构面：断言 `SUMMARY_RULES`／`ERROR_TEXT_RULES` 都不含 PII 规则名（手机号/邮箱/证件/卡号/IP）；
- 行为面：含手机号的无凭据文本，喂进两扇门都逐字等于旧结果、且手机号**原样保留**；
- 词汇面：出口仍是 `[REDACTED]`，不混进引擎默认的 `***`。
"""

from __future__ import annotations

import re

from neurova.context.summarizing_compressor import _redact
from neurova.llm.providers.error_mapping import _mask_secrets
from neurova.security.sensitive_info import ERROR_TEXT_RULES, SUMMARY_RULES

# 单源里属于 PII、**绝不该**被这两扇门接进来的规则名（投影用错＝这几条被拉进来 → 当场红）。
_PII_RULE_NAMES = frozenset({"phone", "email", "id_card", "bank_card", "ip_address"})

# 无凭据的中文运维文本：两扇门都该原样透传。
_CLEAN_OPS_TEXT = "本次部署顺利完成，未触发限流，无需人工干预。"
# 含中国大陆手机号、不含任何凭据：既不该被旧门脱，也不该被新门脱——这条是投影用错的试纸。
_PHONE_NO_CREDENTIAL_TEXT = "告警工单已建，请联系运维 13812345678 复核节点状态。"


# ── 改接前两扇门的在役实现（原样抄自被删的自带表，作期望值） ──

_LEGACY_SUMMARY_PATTERNS = (
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{20,})"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(token\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
)

_LEGACY_ERROR_KEY_PATTERN = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{8,}|nvk_[A-Za-z0-9_-]{8,}|Bearer\s+\S+)"
)


def _legacySummaryRedact(text: str) -> str:
    """摘要门改接前的自写循环（带捕获组 `\1[REDACTED]`、否则整段 `[REDACTED]`）。"""
    result = text or ""
    for pattern in _LEGACY_SUMMARY_PATTERNS:
        if pattern.groups:
            result = pattern.sub(r"\1[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


def _legacyErrorMask(text: str) -> str:
    """错误文案门改接前的 `_KEY_PATTERN.sub("[REDACTED]", …)`。"""
    return _LEGACY_ERROR_KEY_PATTERN.sub("[REDACTED]", text or "")


# 摘要门：逐字相等的输入集（键值式 + 无凭据/PII 文本；独立凭据形状见错误门）。
_SUMMARY_EQUALLY_HANDLED = (
    "配置密钥 api_key=sk-abcdefghijklmnop 后重启服务",
    "轮换仓库令牌 api_key=ghp_AAAAAAAAAAAAAAAAAAAA 完成",
    "重置成功 password=Sup3rSecretValue 完成",
    _CLEAN_OPS_TEXT,
    _PHONE_NO_CREDENTIAL_TEXT,
)

# 错误文案门：逐字相等的输入集（值形状 sk/nvk/Bearer + 键值式里内嵌的 sk + 无凭据/PII 文本）。
# 不含 `ghp_`——旧 `_KEY_PATTERN` 本就没这条，谈不上逐字相等。
_ERROR_EQUALLY_HANDLED = (
    "Bearer a$b",
    "换用 nvk_zzzzzzzzzzzz 稍后重试",
    "err: use sk-1234567890abcdef or abort the request",
    "配置密钥 api_key=sk-abcdefghijklmnop 后重启服务",
    _CLEAN_OPS_TEXT,
    _PHONE_NO_CREDENTIAL_TEXT,
)


class TestLiveRedactionDoorsUseTheSharedEngine:
    def testSummaryDoorMatchesLegacyVerbatim(self):
        """摘要门改接 SUMMARY_RULES 后：在役行为逐字等于旧实现，且 PII 没被接进来。"""
        assert SUMMARY_RULES  # 空投影即失效，先自证非空
        assert _PII_RULE_NAMES.isdisjoint({r.name for r in SUMMARY_RULES}), (
            "SUMMARY_RULES 混进了 PII 规则——手机号那类不该被摘要链接进来"
        )
        for text in _SUMMARY_EQUALLY_HANDLED:
            assert _redact(text) == _legacySummaryRedact(text), text
        # 手机号原样保留（旧门不脱，新门也不得脱）；出口仍是 [REDACTED]、不混入 ***。
        assert "13812345678" in _redact(_PHONE_NO_CREDENTIAL_TEXT)
        redacted_kv = _redact(_SUMMARY_EQUALLY_HANDLED[0])
        assert "[REDACTED]" in redacted_kv and "***" not in redacted_kv

    def testErrorDoorMatchesLegacyVerbatim(self):
        """错误文案门改接 ERROR_TEXT_RULES 后：值形状逐字等于旧实现，PII 没被接进来。"""
        assert ERROR_TEXT_RULES
        assert _PII_RULE_NAMES.isdisjoint({r.name for r in ERROR_TEXT_RULES}), (
            "ERROR_TEXT_RULES 混进了 PII 规则——运维文案里的手机号/IP 是正常信息"
        )
        for text in _ERROR_EQUALLY_HANDLED:
            assert _mask_secrets(text) == _legacyErrorMask(text), text
        assert "13812345678" in _mask_secrets(_PHONE_NO_CREDENTIAL_TEXT)
        redacted_shape = _mask_secrets("Bearer a$b")
        assert "[REDACTED]" in redacted_shape and "***" not in redacted_shape
