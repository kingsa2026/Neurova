# -*- coding: utf-8 -*-
"""外部 Agent 接入协议的判据层（版本协商 / 载荷上限 / 在线态派生）

语义约定：
- 版本协商按「渐进」口径：客户端未声明 supported_versions 时放行，但必须被诚实
  标注为 legacy（不得伪装成协商成功）；声明了但不含服务端 PROTOCOL_VERSION 才拒。
- 载荷上限要**真的执行**。被退役的 communication_protocol.py 里 max_message_size
  只在握手响应中回显（:293），全文件无任何拒绝路径——本模块存在的理由之一就是把
  这个"声明了但从不生效"的口径变成判据。
- 在线态由 last_seen 派生，不新增存储、不新增心跳端点：现役外部 Agent 在握手后
  last_seen 永不更新，status 恒为 "online"，照搬超时判定会把所有 Agent 集体判成
  离线。窗口边界取「达到窗口即 idle」，避免 >= / > 两解。
"""

import json
import time

import pytest

from neurova.api.external_agent_protocol import (
    MAX_MESSAGE_BYTES,
    ONLINE_WINDOW_SECONDS,
    PROTOCOL_VERSION,
    deriveAgentStatus,
    negotiationMode,
    validateMessageSize,
    validateProtocolVersion,
)


# ---------------------------------------------------------------------------
# 版本协商
# ---------------------------------------------------------------------------


def test_negotiated_when_client_supports_server_version():
    """声明了含服务端版本的客户端 → 放行且判为 negotiated。"""
    accepted, reason = validateProtocolVersion(["0.9", PROTOCOL_VERSION])
    assert accepted is True
    assert reason is None
    assert negotiationMode([PROTOCOL_VERSION]) == "negotiated"


def test_legacy_client_without_versions_is_accepted_but_marked_legacy():
    """未声明版本的存量客户端 → 放行，但协商结果必须标 legacy。

    红灯要防的退化：把 legacy 也报成 negotiated，等于让服务端以为对方协商过。
    """
    for absent in (None, []):
        accepted, reason = validateProtocolVersion(absent)
        assert accepted is True, absent
        assert reason is None, absent
        assert negotiationMode(absent) == "legacy"


def test_rejects_when_no_version_overlap():
    """声明了但不含服务端版本 → 拒，且点名实际收到的版本。"""
    accepted, reason = validateProtocolVersion(["2.0", "2.1"])
    assert accepted is False
    assert reason is not None
    assert "2.0" in reason


# ---------------------------------------------------------------------------
# 载荷上限（必须真的拦）
# ---------------------------------------------------------------------------


def test_accepts_payload_at_the_limit_boundary():
    """恰好等于上限 → 放行；比上限少一字节判据必须不同（钉死 <= 与 < 的口径）。"""
    payload = {"blob": "x" * 64}
    size = len(json.dumps(payload).encode("utf-8"))

    okAtLimit, reported = validateMessageSize(payload, limit=size)
    assert okAtLimit is True
    assert reported == size

    okOverLimit, _ = validateMessageSize(payload, limit=size - 1)
    assert okOverLimit is False


def test_rejects_oversized_payload_and_reports_actual_size():
    """超限 → 拒，并回真实序列化字节数（供 413 说明用）。"""
    ok, size = validateMessageSize({"content": "x" * 4096}, limit=64)
    assert ok is False
    assert size > 64


def test_default_limit_is_the_declared_constant():
    """默认上限取 MAX_MESSAGE_BYTES，握手回显与拦截必须同源于此常量。"""
    ok, _ = validateMessageSize({"k": "v" * (MAX_MESSAGE_BYTES + 1024)})
    assert ok is False


# ---------------------------------------------------------------------------
# 在线态派生
# ---------------------------------------------------------------------------


def test_online_within_window():
    now = time.time()
    assert deriveAgentStatus(now - 10, now) == "online"


def test_idle_once_window_reached():
    """边界口径钉死：恰好达到窗口即 idle。"""
    now = time.time()
    assert deriveAgentStatus(now - ONLINE_WINDOW_SECONDS, now) == "idle"


def test_idle_when_never_seen():
    """从未活动（0 值）不得被判成 online。"""
    now = time.time()
    assert deriveAgentStatus(0.0, now) == "idle"
