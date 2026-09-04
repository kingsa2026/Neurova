"""声明式 provider compat 开关测试（OpenClaw 启发 P0-2）

背景：docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-2。
per-provider 兼容逻辑从散落 if 分支收编为 ProviderCompat 描述表；
请求构造（llm_client 两处 stream_options）声明式消费 cfg.compat。
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock

from neurova.llm.provider_compat import ProviderCompat, resolve_compat


class TestProviderCompatTable(unittest.TestCase):
    """描述表解析：id > host > 默认；显式声明覆盖静态表。"""

    def test_resolve_by_provider_id(self):
        c = resolve_compat(provider_id="sensetime")
        self.assertFalse(c.include_stream_usage, "sensetime 网关必须关闭 include_usage")

    def test_resolve_by_base_url_host(self):
        c = resolve_compat(base_url="https://token.sensenova.cn/v1")
        self.assertFalse(c.include_stream_usage)

    def test_unknown_provider_defaults_open(self):
        c = resolve_compat(provider_id="unknown-p", base_url="https://api.some.one/v1")
        self.assertTrue(c.include_stream_usage, "未收录 provider 默认 OpenAI 协议行为")

    def test_explicit_dict_overrides_table(self):
        """ProviderConfig 显式声明字段级覆盖静态表。"""
        c = resolve_compat(provider_id="sensetime", compat_dict={"include_stream_usage": True})
        self.assertTrue(c.include_stream_usage)

    def test_dataclass_frozen(self):
        with self.assertRaises(Exception):
            ProviderCompat(include_stream_usage=True).include_stream_usage = False  # type: ignore


class TestLLMClientCompatWiring(unittest.TestCase):
    """LLMClient 请求构造声明式消费 cfg.compat（两处 stream_options）。"""

    def _client(self, compat: ProviderCompat):
        from neurova.llm_client import LLMClient, LLMConfig

        cfg = LLMConfig(api_key="sk-test", base_url="https://example.com/v1", model="m")
        client = LLMClient.__new__(LLMClient)
        client.config = cfg
        client.logger = MagicMock()
        client.client = MagicMock()
        client.async_client = MagicMock()  # 独立 mock，避免同步/异步互覆
        client._stats = {"total_calls": 0, "successful_calls": 0, "failed_calls": 0, "total_tokens": 0, "total_time": 0.0}
        cfg.compat = compat

        captured = {}

        def fake_create(**params):
            captured.update(params)

            class _Chunk:
                choices = []
                usage = None
                model = "m"
                id = "r1"

            return iter([_Chunk()])

        async def fake_create_async(**params):
            captured.update(params)

            class _Chunk:
                choices = []
                usage = None
                model = "m"
                id = "r1"

            async def _agen():
                yield _Chunk()

            return _agen()

        client.client.chat.completions.create = fake_create
        client.async_client.chat.completions.create = fake_create_async
        return client, captured

    def test_stream_options_included_when_compat_on(self):
        from neurova.llm_client import LLMConfig

        client, captured = self._client(ProviderCompat(include_stream_usage=True))
        list(client.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(captured.get("stream_options"), {"include_usage": True})

    def test_stream_options_omitted_when_compat_off(self):
        client, captured = self._client(ProviderCompat(include_stream_usage=False))
        list(client.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertNotIn("stream_options", captured, "compat 关闭时不得发送 stream_options")

    def test_async_stream_options_omitted_when_compat_off(self):
        client, captured = self._client(ProviderCompat(include_stream_usage=False))

        async def _run():
            async for _ in client.chat_stream_async([{"role": "user", "content": "hi"}]):
                pass

        asyncio.run(_run())
        self.assertNotIn("stream_options", captured)

    def test_config_default_has_compat(self):
        """LLMConfig 默认带 compat（默认 ProviderCompat，不破坏存量构造）。"""
        from neurova.llm_client import LLMConfig

        self.assertIsInstance(LLMConfig().compat, ProviderCompat)


class TestModelClientCreationWiring(unittest.TestCase):
    """multi_model_client._create_model_client 解析 provider compat 注入 LLMConfig。"""

    def test_create_model_client_resolves_compat(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.provider_manager import ProviderConfig

        mgr = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mgr._clients = {}
        mgr._init_lock = MagicMock()
        mgr._init_lock.__enter__ = MagicMock(return_value=None)
        mgr._init_lock.__exit__ = MagicMock(return_value=False)

        provider = ProviderConfig(
            id="sensetime", name="SenseTime", provider="openai",
            base_url="https://token.sensenova.cn/v1", api_key="sk-x",
            models=["sensechat-5"], default_model="sensechat-5",
        )
        captured_cfg = {}

        import neurova.llm.multi_model_client as mmc

        real_llm_client_cls = mmc.LLMClient

        class SpyClient(real_llm_client_cls):
            def __init__(self, config, preset=None):
                captured_cfg["compat"] = config.compat
                super().__init__(config, preset)

        with unittest.mock.patch.object(mmc, "LLMClient", SpyClient):
            mc = mgr._create_model_client(provider, "sensechat-5")

        self.assertIsNotNone(mc)
        self.assertFalse(captured_cfg["compat"].include_stream_usage)


if __name__ == "__main__":
    unittest.main()
