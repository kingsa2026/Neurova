# -*- coding: utf-8 -*-
"""CHAN-02：微信二维码扫码授权的 base_url 必须过 SSRF 单源守卫。

审计证据（docs/05-reports/全仓逐文件审计报告_2026-11-25.md §8 CHAN-02）：
`WeChatQRCodeAuthHandler._get_base_url` 接受任意 `base_url` 查询参数，服务端
直接 GET 且 `follow_redirects=True`——任何登录用户可借服务端网络能力探测内网、
读取云元数据，且 302 可把公网首跳绕进环回。

判据：
1. 私网/环回/元数据/非法 scheme 的 base_url 必须在发请求**之前**被拒（400），
   用真 `url_guard` 判定，不用 mock 冒充；
2. 合法 base_url 的请求走 `safe_fetch` 单源（逐跳 redirect 复核），不再直用
   httpx 自动跟随；
3. 未指定 base_url 时回落到官方端点，既存行为不变。
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(base_url: str = "") -> Request:
    query = f"base_url={quote(base_url, safe='')}" if base_url else ""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/channel-configs/wechat/qrcode",
            "query_string": query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
    )


def _handler():
    from neurova.channels.qrcode_auth import WeChatQRCodeAuthHandler

    return WeChatQRCodeAuthHandler()


class TestBaseUrlRejectedBeforeAnyRequest:
    """base_url 是用户可控输入：内网目标必须在出网前拒绝。"""

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://127.0.0.1:8080",
            "http://localhost:9",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.5",
            "http://192.168.1.1",
            "file:///etc/passwd",
            "gopher://127.0.0.1:6379",
        ],
    )
    def test_blockedTargetsRaise400(self, base_url, monkeypatch):
        # 已存配置不是本判据的来源：固定为空，避免真实数据根干扰
        import neurova.api.endpoints.channel_config as channel_config

        monkeypatch.setattr(channel_config, "_load_configs", lambda: {})

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_handler()._get_base_url(_request(base_url)))
        assert excinfo.value.status_code == 400, (
            f"内网/非法 base_url 未被拒绝（实得 {excinfo.value.status_code}）: {base_url}"
        )

    def test_defaultFallsBackToOfficialHost(self, monkeypatch):
        import neurova.api.endpoints.channel_config as channel_config
        from neurova.channels.qrcode_auth import ILINK_DEFAULT_BASE_URL

        monkeypatch.setattr(channel_config, "_load_configs", lambda: {})
        assert asyncio.run(_handler()._get_base_url(_request())) == ILINK_DEFAULT_BASE_URL


class TestFetchGoesThroughSafeFetch:
    """请求必须走 safe_fetch（逐跳 redirect 复核），不得再直用 httpx 跟随。"""

    def testFetchUsesSafeFetchSingleSource(self, monkeypatch):
        import neurova.security.safe_fetch as safe_fetch_module

        calls = []

        class _FakeResponse:
            status = 200

            def json(self):
                return {"qrcode": "qr-token-1", "qrcode_img_content": ""}

        def _fakeSafeFetch(url, **kwargs):
            calls.append((url, kwargs))
            return _FakeResponse()

        # 本判据钉的是「请求走 safe_fetch 单源」，公网解析不是它主张的事
        monkeypatch.setattr(safe_fetch_module, "assertHopAllowed", lambda url: None)
        monkeypatch.setattr(safe_fetch_module, "safe_fetch", _fakeSafeFetch)

        result = asyncio.run(_handler().fetch_qrcode(_request("https://ilink.example.com")))

        assert result.poll_token == "qr-token-1"
        assert calls and calls[0][0].startswith("https://ilink.example.com/ilink/bot/get_bot_qrcode"), (
            f"二维码请求没有走 safe_fetch 单源（实际调用: {calls}）"
        )