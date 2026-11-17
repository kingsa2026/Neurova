# -*- coding: utf-8 -*-
"""N2（2026-11-17）——set_webhook 的本地验签状态只随 Telegram 侧真实结果落地。

此前 `set_webhook` 先写 `self._webhook_url/_webhook_secret` 再调 Telegram API：
API 失败（token 错、网络断）时本地仍留着这份 secret——本端验签面与平台侧事实
不一致（平台根本没配这个 webhook）。改为成功后才写：失败时保留原值。
"""

import pytest

from neurova.channels.telegram_webhook import TelegramWebhookMixin


class _StubAdapter(TelegramWebhookMixin):
    """只装 mixin 的桩：_api_request 按预设返回，不碰网络。"""

    def __init__(self, ok: bool):
        self.bot_token = "123:stub"
        self._webhook_url = ""
        self._webhook_secret = "old-secret"
        self._ok = ok
        self.calls = []

    def _api_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"ok": self._ok, "result": True}


class TestSetWebhookLocalStateFollowsPlatformTruth:
    def testSuccessPersistsUrlAndSecret(self):
        adapter = _StubAdapter(ok=True)

        assert adapter.set_webhook("https://example.com/tg", "new-secret") is True
        assert adapter._webhook_url == "https://example.com/tg"
        assert adapter._webhook_secret == "new-secret"

    def testFailureKeepsPreviousState(self):
        adapter = _StubAdapter(ok=False)

        assert adapter.set_webhook("https://example.com/tg", "new-secret") is False
        assert adapter._webhook_url == "", "API 失败不该写 _webhook_url"
        assert adapter._webhook_secret == "old-secret", "API 失败不该覆盖既有 _webhook_secret"

    def testRequestGoesToSetWebhookWithSecret(self):
        adapter = _StubAdapter(ok=True)

        adapter.set_webhook("https://example.com/tg", "s9")

        method, path, kwargs = adapter.calls[0]
        assert method == "POST" and path.endswith("/setWebhook")
        assert kwargs["json"] == {"url": "https://example.com/tg", "secret_token": "s9"}

    def testEmptySecretOmittedFromPayload(self):
        adapter = _StubAdapter(ok=True)

        adapter.set_webhook("https://example.com/tg", "")

        assert adapter.calls[0][2]["json"] == {"url": "https://example.com/tg"}
