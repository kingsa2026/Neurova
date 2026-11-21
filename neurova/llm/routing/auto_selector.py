# -*- coding: utf-8 -*-
"""auto 请求的能力驱动选型（R3，参照系 ad 追平批一）。

仅服务「未显式钉死模型/服务商」的 auto 请求：按本轮需求能力（如带工具
→ TOOL_USE）从路由表选型；选不出可满足候选时返回 None，调用方保持既有
兜底链（MultiModelLLMClient 自愈/跨服务商回退），不凭空造能力。
命中时调用方只传模型名、不携带 provider_id（与视觉轮覆盖同理由：钉死
provider 会禁用 auto-failover）。
"""
from __future__ import annotations

from typing import Any, Optional, Tuple


def _selectChatCandidate(scope: Optional[str], needs_tools: bool) -> Any:
    """路由层选型（模块级缝，测试可替换）。"""
    from neurova.llm.llm_router import (
        ModelCapability,
        RequestType,
        select_model_for_request,
    )

    required = [ModelCapability.TOOL_USE] if needs_tools else None
    return select_model_for_request(
        RequestType.CHAT, required_capabilities=required, scope=scope or None
    )


def resolveAutoChatModel(
    *,
    scope: Optional[str] = None,
    needs_tools: bool = False,
) -> Optional[Tuple[str, str]]:
    """为 auto 请求选型，返回 (provider_id, model)；无候选/路由不可用 → None。"""
    try:
        selected = _selectChatCandidate(scope, needs_tools)
    except Exception:  # noqa: BLE001 — 选型失败回既有兜底，不炸调用链
        return None
    if selected is None:
        return None
    return selected.provider_id, selected.model
