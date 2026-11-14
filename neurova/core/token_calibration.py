# -*- coding: utf-8 -*-
"""A1（对照改进追问批）：token 尺子按模型校准。

## 为什么

全仓压缩判据（折叠触发线、microcompact、召回额度）都用同一把估算尺
（`context/token_estimator.py`，tiktoken o200k）。o200k 对 OpenAI 系文本
是精确的，但对 Claude/Gemini 等自家分词器模型存在系统性偏差（实测可达
10-30%）——尺子偏差会沿判据链放大：估算偏低 ⇒ 所有阈值实际偏松 ⇒
超窗风险整体上升。服务商回传的 usage 是**账单真值**，用它校准尺子。

## 净信号采样

完成侧（output）是最纯净的偏差信号：账单 `completion_tokens` 与**同一段
输出文本**的尺子估算之比，就是该模型的分词偏差，不含 system/工具描述
等混杂项。含工具调用参数的响应跳过（账单含参数 JSON，会污染文本偏差）。

## 两步走纪律

观测面常开（每模型样本数/偏差进 snapshot）；**预算校准只在证据足够时
生效**：样本 ≥5 且偏差超出 ±15% 带才应用（否则因子中性 1.0）。
因子钳 [0.5, 2.0]。开关 NEUROVA_TOKEN_CALIBRATION=0 全关。
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

_LOCK = threading.RLock()
# model -> {"samples": int, "bias_sum": float}
_SAMPLES: Dict[str, Dict[str, float]] = {}

_MIN_SAMPLES = 5          # 证据门槛：样本不足不改判据
_APPLY_BAND = 0.15        # 偏差带：±15% 以内视为尺子可用
_CLAMP_LO, _CLAMP_HI = 0.5, 2.0   # 因子钳位（防极端样本劫持判据）


def enabled() -> bool:
    """总开关：默认开（采样+证据门槛校准）；NEUROVA_TOKEN_CALIBRATION=0 全关。"""
    return os.environ.get("NEUROVA_TOKEN_CALIBRATION", "1") != "0"


def wantsSample(model: str) -> bool:
    """流式路径用：该模型是否还需要采样（样本够后就地停采，零开销）。"""
    if not enabled():
        return False
    with _LOCK:
        return _SAMPLES.get(str(model or ""), {}).get("samples", 0) < _MIN_SAMPLES


def recordOutputSample(
    model: str,
    output_text: str,
    billed_completion_tokens: int,
    has_tool_calls: bool = False,
) -> None:
    """记一个（尺子估算, 账单真值）样本（完成侧）。

    - output_text：assistant 输出全文（content + reasoning_content）；
    - billed_completion_tokens：usage.completion_tokens 账单真值；
    - has_tool_calls=True 时跳过（账单含工具参数 JSON，污染文本偏差）。
    """
    if not enabled():
        return
    model = str(model or "").strip()
    billed = int(billed_completion_tokens or 0)
    text = str(output_text or "")
    if not model or billed <= 0 or not text.strip() or has_tool_calls:
        return
    from neurova.context.token_estimator import estimate_tokens

    estimated = int(estimate_tokens(text))
    if estimated <= 0:
        return
    bias = billed / estimated
    # 离群样本**截尾入均值**（winsorize）：真有极端分词偏差的模型仍能校准到
    # 钳位边界，而单次网关错账也不会把均值劫持出界。
    bias = min(_CLAMP_HI, max(_CLAMP_LO, bias))
    with _LOCK:
        entry = _SAMPLES.setdefault(model, {"samples": 0, "bias_sum": 0.0})
        entry["samples"] += 1
        entry["bias_sum"] += bias


def factorFor(model: str) -> float:
    """该模型的尺子校准因子（1.0 = 中性，不改判据）。

    样本 ≥5 且偏差超出 ±15% 带才返回实测值（钳 [0.5, 2.0]）；否则 1.0。
    """
    if not enabled():
        return 1.0
    with _LOCK:
        entry = _SAMPLES.get(str(model or "").strip())
        if not entry or entry["samples"] < _MIN_SAMPLES:
            return 1.0
        bias = entry["bias_sum"] / entry["samples"]
    if abs(bias - 1.0) <= _APPLY_BAND:
        return 1.0
    return min(_CLAMP_HI, max(_CLAMP_LO, bias))


def snapshot() -> Dict[str, Dict[str, Any]]:
    """读数面：每模型 {samples, bias, factor, applied}。"""
    out: Dict[str, Dict[str, Any]] = {}
    with _LOCK:
        models = list(_SAMPLES.keys())
    for model in models:
        factor = factorFor(model)
        with _LOCK:
            entry = _SAMPLES.get(model, {})
            samples = int(entry.get("samples", 0))
            bias = (entry.get("bias_sum", 0.0) / samples) if samples else None
        out[model] = {
            "samples": samples,
            "bias": round(bias, 4) if bias is not None else None,
            "factor": round(factor, 4),
            "applied": factor != 1.0,
        }
    return out


def resetForTests() -> None:
    with _LOCK:
        _SAMPLES.clear()
