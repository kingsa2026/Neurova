# -*- coding: utf-8 -*-
"""shared_with 租户段（可靠性方案 §8-E1）。

用户 id 与 `tenant:<id>` 段在 `shared_with` 同列共存：段是唯一构造/判别入口，
消费方（repository / fts_index / 端点层）不得各自手写前缀字面量——
单一事实源（修复教义第 6 条）。
"""

from __future__ import annotations

TENANT_SEGMENT_PREFIX = "tenant:"


def tenantSegment(tenantId: str) -> str:
    """租户 id → shared_with 段。"""
    return TENANT_SEGMENT_PREFIX + str(tenantId or "default")


def isTenantSegment(value: str) -> bool:
    return str(value or "").startswith(TENANT_SEGMENT_PREFIX)


def tenantOfSegment(value: str) -> str:
    """段 → 租户 id；非段原值返回空串。"""
    value = str(value or "")
    return value[len(TENANT_SEGMENT_PREFIX):] if isTenantSegment(value) else ""
