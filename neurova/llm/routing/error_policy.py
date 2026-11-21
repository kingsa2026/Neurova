# -*- coding: utf-8 -*-
"""路由错误语义表（R1，参照系 ad 追平批一）。

一个错误该「换下家（FALLBACK）」「原地等重试（RETRY_SAME）」还是「就此
打住（STOP）」，只在这里回答（教义第 6 条单一事实源）。错误分类事实仍
出自 neurova.llm.model_error_policy.classify_model_error（八类），本模块
只做「类 → 路由决策」映射。全仓消费方（教义第 5 条全命中点扫荡）：
- MultiModelLLMClient.chat() 跨模型回退（原 model_error_policy.is_fallback_eligible）
- MultiModelLLMClient.chat_stream() 切换容错（原硬编码三类 kind 元组）
两条路径从此读同一张表。

语义（对齐专项细拆轴 4/5 的对方已验证语义，2026-11-22）：
- rate_limited → RETRY_SAME：同模型等待重试（429 预算内）优先；预算耗尽
  后仍可 FALLBACK——故 is_fallback_eligible 对 429 恒 True，与旧约一致。
- transient（超时/连接/5xx，含 408/409/423/425 这类"换家可活"的网关态）
  / model_not_found / authentication → FALLBACK。**契约变更**：authentication
  由「不回退」（B1-2 旧约）改「可回退」——旧理由"换模型同样 401"只在单
  provider 内成立；多服务商各持独立 key 时换家能真解决 key 失效，且
  auto_failover 仅作用于未显式钉死 provider 的请求，存量钉死行为不变。
- context_overflow / content_safety / bad_request / insufficient_balance /
  unknown → STOP：换模型无意义或应诚实失败。
"""
from __future__ import annotations

import enum
from typing import Union

from neurova.llm.model_error_policy import classify_model_error

#: 允许跨模型/跨服务商回退的错误类（封闭集；/authentication 为 2026-11-22
#: 契约变更，见模块 docstring）。
FALLBACK_ELIGIBLE_KINDS = frozenset({
    "rate_limited",
    "transient",
    "model_not_found",
    "authentication",
})

#: 唯一"先原地重试"的类：429 同模型等待重试（预算与次数由调用方的
#: 429 配置管，这里只给语义建议）。
RETRY_SAME_KIND = "rate_limited"


class RouteDecision(enum.Enum):
    """错误路由决策（封闭集，无第四种）。"""

    FALLBACK = "fallback"          # 换下一个候选模型/服务商
    RETRY_SAME = "retry_same"      # 先原地等待重试（429 预算内），耗尽仍可 FALLBACK
    STOP = "stop"                  # 就此打住：换模型无意义或应诚实失败


def decideRoute(error: Union[BaseException, str]) -> RouteDecision:
    """按错误分类给出路由决策（分类事实单源在 model_error_policy）。"""
    kind = classify_model_error(error).kind
    if kind == RETRY_SAME_KIND:
        return RouteDecision.RETRY_SAME
    if kind in FALLBACK_ELIGIBLE_KINDS:
        return RouteDecision.FALLBACK
    return RouteDecision.STOP


def is_fallback_eligible(error: Union[BaseException, str]) -> bool:
    """是否允许尝试下一个候选（RETRY_SAME 预算耗尽后同样放行）。"""
    return decideRoute(error) is not RouteDecision.STOP


def retry_same_model(error: Union[BaseException, str]) -> bool:
    """是否建议先在同模型上等待重试（仅 429）。"""
    return decideRoute(error) is RouteDecision.RETRY_SAME
