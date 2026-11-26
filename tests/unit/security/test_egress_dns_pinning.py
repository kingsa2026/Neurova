# -*- coding: utf-8 -*-
"""CORE-20 R5：校验后直发的普通 HTTP 入口统一使用 safe_fetch。"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from neurova.security.safe_fetch import SafeFetchResponse


def _response(content=b"ok", status=200, headers=None):
    return SafeFetchResponse(status, headers or {}, content, "http://1.2.3.4/result")


def testKnowledgeUrlFetchUsesSafeFetch(monkeypatch):
    from neurova.api.endpoints import knowledge_ingestion as ingestion

    calls = []

    def fake_safe_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return _response(b"<p>knowledge</p>")

    def forbid_urlopen(*args, **kwargs):
        raise AssertionError("知识导入不得绕过 safe_fetch 直连")

    monkeypatch.setattr("neurova.security.safe_fetch.safe_fetch", fake_safe_fetch)
    monkeypatch.setattr("urllib.request.urlopen", forbid_urlopen)

    assert ingestion._fetch_url("http://1.2.3.4/page") == b"<p>knowledge</p>"
    assert calls[0][1]["max_bytes"] == 1024 * 1024


def testMarketAdapterUsesSafeFetch(monkeypatch):
    from neurova.skills import market_adapters as adapters

    calls = []

    def fake_safe_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return _response(b"market")

    monkeypatch.setattr("neurova.security.safe_fetch.safe_fetch", fake_safe_fetch)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("市场下载绕过 safe_fetch"))

    assert adapters.SkillsShAdapter()._http_get("http://1.2.3.4/skill") == b"market"
    assert calls[0][1]["timeout"] == adapters.MARKET_FETCH_TIMEOUT_SECONDS


def testHubClientUsesSafeFetch(monkeypatch):
    from neurova.skills import hub_client as hub

    calls = []

    def fake_safe_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return _response(b"hub")

    monkeypatch.setattr("neurova.security.safe_fetch.safe_fetch", fake_safe_fetch)
    monkeypatch.setattr(hub, "urlopen", lambda *a, **k: pytest.fail("Hub 下载绕过 safe_fetch"), raising=False)

    assert hub._http_fetch("http://1.2.3.4/skill", timeout=2.0) == b"hub"
    assert calls[0][1]["headers"]["Accept"] == "application/json"


def testIlinkMediaUrlUsesSafeFetch(monkeypatch):
    from neurova.channels import wechat_media

    adapter = SimpleNamespace(
        _ilink_initialized=True,
        ILINK_API_BASE="https://ilink.example",
        ilink_bot_token="token",
    )
    media = wechat_media.WeChatMediaMixin(adapter)
    requestsCalls = []
    safeCalls = []

    def fake_requests_get(url, **kwargs):
        requestsCalls.append(url)
        return SimpleNamespace(json=lambda: {"success": True, "url": "http://1.2.3.4/media"})

    def fake_safe_fetch(url, **kwargs):
        safeCalls.append((url, kwargs))
        return _response(b"media-bytes")

    monkeypatch.setattr(wechat_media, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(wechat_media.requests, "get", fake_requests_get)
    monkeypatch.setattr("neurova.security.safe_fetch.safe_fetch", fake_safe_fetch)

    assert media._download_ilink_media("media-id") == b"media-bytes"
    assert requestsCalls == ["https://ilink.example/media/get"]
    assert safeCalls[0][0] == "http://1.2.3.4/media"


def testSchedulerWebhookUsesSafeFetch(monkeypatch):
    from neurova.agent import scheduler
    calls = []

    def fake_safe_fetch(url, **kwargs):
        calls.append((url, kwargs))
        return _response(b'{"ok": true}', headers={"content-type": "application/json"})

    class ForbiddenAiohttp:
        class ClientSession:
            async def __aenter__(self):
                pytest.fail("调度 webhook 不得绕过 safe_fetch 直连")

            async def __aexit__(self, *args):
                return False

    monkeypatch.setitem(sys.modules, "aiohttp", ForbiddenAiohttp)
    monkeypatch.setattr("neurova.security.safe_fetch.safe_fetch", fake_safe_fetch)
    task = scheduler.AutomationTask(
        id="wh-1", name="webhook", type=scheduler.TaskType.WEBHOOK,
        request=scheduler.TaskRequest(
            type=scheduler.TaskType.WEBHOOK,
            webhook_url="http://1.2.3.4/hook",
            input={"event": "tick"},
        ),
    )
    execution = scheduler.TaskExecution(
        id="run-1", task_id="wh-1", status=scheduler.TaskStatus.RUNNING,
    )

    result = asyncio.run(scheduler.WebhookTaskExecutor().execute(task, execution))

    assert result["success"] is True
    assert result["result"] == {"ok": True}
    assert json.loads(calls[0][1]["data"]) == {"event": "tick"}
    assert calls[0][1]["method"] == "POST"


def testNeurflowRequestPassesValidatedAddressPlan(monkeypatch):
    from neurova import http_fetch
    from neurova.collaboration.neurflow import builtin

    calls = []

    def fake_request_once(url, **kwargs):
        calls.append((url, kwargs))
        return http_fetch.HopResult(200, {"content-type": "text/plain"}, b"flow", None)

    monkeypatch.setattr(http_fetch, "request_once", fake_request_once)
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: pytest.fail("NeurFlow 不得直连"))

    response = builtin._safe_request("GET", "http://1.2.3.4/flow")

    assert response.text == "flow"
    assert calls[0][1]["resolution"].addresses == ("1.2.3.4",)

