# -*- coding: utf-8 -*-
"""RateLimitMiddleware 作为唯一限流执行点的渠道感知行为

背景（活体实测推翻的前提）：全站早在 `middleware.py:226` 挂着按 **client IP**、
硬编码 120/分的限流中间件，且它在 handler 之前执行。因此"在端点里再查一次
firewall 额度"永远轮不到触发——接了不生效，正是本仓禁止的断点形态。
收口方式：限流只有这一个执行点，额度全部取自 `core.firewall`，按路径分渠道。

约定：
- `/api/v1/agent-communication/*` → externalAgent 档；其余 → internal 档。
- internal 档默认值必须等于中间件此前硬编码的 120/分，**不得**因为收口而把人用
  流量收紧（今天 120 在生效，firewall 里那个 60 从来没有调用方）。
- 拒绝时仍返回既有信封 `{"code": 4290, ...}` 并带 Retry-After，避免打断现存客户端。
- 配额键：已解析出身份就按身份，否则回退 client IP —— 不在中间件里另起一套
  JWT 解析（那会是第三条凭证路径）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.middleware import RateLimitMiddleware
from neurova.core.firewall import CHANNEL_EXTERNAL_AGENT, CHANNEL_INTERNAL


class RecordingLimiter:
    """假限额器：记录 (配额键, 渠道) 并按 min 阈值拦。"""

    def __init__(self, limit):
        self.limit = limit
        self.calls = []
        self._counts = {}

    def check_rate_limit(self, quotaKey, channel):
        self.calls.append((quotaKey, channel))
        bucket = (quotaKey, channel)
        used = self._counts.get(bucket, 0)
        if used >= self.limit:
            return False, f"Rate limit exceeded (per minute, channel={channel})"
        self._counts[bucket] = used + 1
        return True, ""

    def get_effective_rules(self, quotaKey):
        return {
            "rate_limit_per_minute": self.limit,
            "external_rate_limit_per_minute": self.limit,
        }


@pytest.fixture()
def app_with_limiter():
    limiter = RecordingLimiter(limit=2)
    app = FastAPI()

    @app.get("/api/v1/agent-communication/ping")
    async def agentPing():
        return {"code": 0, "data": "agent"}

    @app.get("/api/v1/notes/ping")
    async def notesPing():
        return {"code": 0, "data": "notes"}

    # limiter 经构造注入：中间件是唯一的限流执行点，不再有第二处 handler 级检查。
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    return app, limiter


def test_agent_communication_path_uses_external_channel(app_with_limiter):
    app, limiter = app_with_limiter
    client = TestClient(app)

    assert client.get("/api/v1/agent-communication/ping").status_code == 200

    channels = [call[1] for call in limiter.calls]
    assert channels == [CHANNEL_EXTERNAL_AGENT]


def test_other_paths_stay_on_internal_channel(app_with_limiter):
    app, limiter = app_with_limiter
    client = TestClient(app)

    assert client.get("/api/v1/notes/ping").status_code == 200

    channels = [call[1] for call in limiter.calls]
    assert channels == [CHANNEL_INTERNAL]


def test_third_agent_request_is_denied_with_legacy_envelope_and_retry_after(app_with_limiter):
    app, limiter = app_with_limiter
    client = TestClient(app)

    assert client.get("/api/v1/agent-communication/ping").status_code == 200
    assert client.get("/api/v1/agent-communication/ping").status_code == 200

    denied = client.get("/api/v1/agent-communication/ping")
    assert denied.status_code == 429
    # 现存客户端按 code 4290 判限流，信封形态不得改
    assert denied.json()["code"] == 4290
    assert "retry-after" in {k.lower() for k in denied.headers}


def test_channels_have_independent_buckets(app_with_limiter):
    """同键不同渠道互不扣额：外部档打满不应连带饿死人用档。"""
    app, limiter = app_with_limiter
    client = TestClient(app)

    client.get("/api/v1/agent-communication/ping")
    client.get("/api/v1/agent-communication/ping")
    assert client.get("/api/v1/agent-communication/ping").status_code == 429

    assert client.get("/api/v1/notes/ping").status_code == 200


def test_quota_key_falls_back_to_client_ip_without_identity(app_with_limiter):
    app, limiter = app_with_limiter
    client = TestClient(app)

    client.get("/api/v1/notes/ping")
    keys = [call[0] for call in limiter.calls]
    assert keys == ["testclient"], "无身份时必须回退到 IP，不得塌缩成共享默认桶"
