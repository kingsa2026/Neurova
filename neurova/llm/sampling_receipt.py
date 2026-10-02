# -*- coding: utf-8 -*-
"""网关把采样值钉死时的回执处置（T-18 · 工单集 §42）。

钉死是 **per-model** 事实，而提前知道它的三条路都实测不存在：模型档案
`supported_sampling_parameters` 只列名字不列值域且全仓零消费方；
`ProviderCompat` 只有 per-provider / per-host / per-protocol 三个维度，装不下
逐模型的值域；按 provider 一刀切不发会在 A2 量测里误伤 5 个明确受理
`temperature=0.7` 的模型。剩下的唯一信息源是网关自己的 400 回执。

本模块把回执接成闭环：**回执点名哪个键被钉死 → 按 `provider_id:model` 学进
进程级能力缓存（带 TTL）→ 装配处按学习态摘键**。学习一次即长期生效，
TTL 到期后重新观察，上游放宽了我们也跟着放宽。

摘掉而不是改发网关点名的合法值：两者对最终解码行为等价，但后者要把
"only 1 is allowed" 这句文案继续解析成数值，把耦合从字段名扩到值语法上。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from neurova.llm.model_capability_cache import (
    CAP_REJECTED_SAMPLING_PARAMS,
    get_capability_cache,
)

# 咽喉会代发的采样旋钮（单源：别名表、摘键面、判据都从这里派生）。
# max_tokens 不在册——摘它会改变输出预算语义，不是同一类钉子。
SAMPLING_PARAM_KEYS: Tuple[str, ...] = (
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
)

# 网关回执里的字段名与线上键拼写不一致（`TopP` vs `top_p`），别名由在册键
# 去掉分隔符归一后派生——绝不再立第二份名单，否则两份必然漂移。
_RECEIPT_ALIASES: Dict[str, str] = {
    re.sub(r"[^a-z0-9]", "", key.lower()): key for key in SAMPLING_PARAM_KEYS
}

# 实测回执形态：`field Temperature invalid, only 1 is allowed for this model`
_PINNED_FIELD = re.compile(r"field\s+([A-Za-z_][A-Za-z0-9_]*)\s+invalid", re.IGNORECASE)


def _normalize(param: str) -> str:
    return re.sub(r"[^a-z0-9]", "", param.lower())


def rejectedSamplingParam(message: Optional[str]) -> Optional[str]:
    """从网关回执里取出被钉死的采样键；认不出或不在册一律返回 None。

    返回 None 是"没拿到事实"，不是"事实是没有"——调用方据此原样上抛，
    绝不把未知失败当成可以摘键重发的信号（那会退化成盲重试）。
    """
    if not message:
        return None
    named = _PINNED_FIELD.search(message)
    if named is None:
        return None
    return _RECEIPT_ALIASES.get(_normalize(named.group(1)))


def _learnedRejections(model_key: str) -> frozenset:
    learned = get_capability_cache().get(model_key, CAP_REJECTED_SAMPLING_PARAMS)
    return frozenset(learned or ())


def dropLearnedSamplingParams(
    params: Dict[str, Any],
    model_key: str,
    logger=None,
    where: str = "",
) -> Tuple[str, ...]:
    """按已学得的钉子摘掉本模型携带不了的采样键，就地改 *params* 并返回被摘的键名。"""
    dropped = []
    for key in _learnedRejections(model_key):
        if key in params:
            del params[key]
            dropped.append(key)
    if dropped and logger is not None:
        logger.debug(
            "%s: %s 按回执学习态摘掉被钉死的采样键 %s",
            where or "?", model_key, sorted(dropped),
        )
    return tuple(sorted(dropped))


def learnRejectedParam(
    exc: BaseException,
    params: Dict[str, Any],
    model_key: str,
    logger=None,
    where: str = "",
) -> bool:
    """*exc* 是"某采样字段被这个模型钉死"时：学进缓存并摘掉该键。

    返回 True 表示本次请求确实多带了一颗钉子且已摘掉（调用方应当重发）；
    返回 False 表示这不是钉子失败，或该键已不在本次请求里——后一句正是摘键
    循环的终止条件：每轮 *params* 严格变小，所以循环上界是请求携带的键数。
    """
    key = rejectedSamplingParam(getattr(exc, "message", None) or str(exc))
    if key is None or key not in params:
        return False
    del params[key]
    get_capability_cache().learn(
        model_key, CAP_REJECTED_SAMPLING_PARAMS, _learnedRejections(model_key) | {key},
    )
    if logger is not None:
        logger.warning(
            "%s: 网关把 %s 的 %s 钉死（%s）——已学进能力缓存并摘键重发",
            where or "?", model_key, key, str(exc)[:200],
        )
    return True
