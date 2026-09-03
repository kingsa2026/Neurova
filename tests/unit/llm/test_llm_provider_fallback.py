"""
TDD 回归测试: MultiModelLLMClient 的 provider 兜底 (fallback) 机制

文件路径: tests/unit/llm/test_llm_provider_fallback.py

背景 (bug: "[LLM Error] No client available" 的新根因):
- 服务器启动时默认服务商（如 sensetime，优先级最高 priority=20）可能没有 api_key，
  而其他有效服务商（如 b.ai）反而有 key。
- 旧逻辑:
    1. `_initialize_default_clients()`: 默认服务商无 key → 直接 return → _clients 恒为空
    2. `_get_client_for_request()`: 严格按请求的 provider/model 查找 → 永远拿不到客户端
       （agent 配置常指向无 key 的服务商，如 kai 指定 provider=sensetime）
  → chat() 返回 {"error": "No client available"} → AgentLLMClient 包装为
    "[LLM Error] No client available"

修复方案 (宽容兜底, 不抹除根因日志):
1. `_initialize_default_clients()`: 默认服务商无 key 时回退到任意 enabled 且有 key 的服务商
   (新增 `_find_kvable_provider()`), 无任何有 key provider 时才停止并打 ERROR
2. 新增 `_resolve_available_fallback()`: 统一兜底入口
   - get_current_client() 优先; _clients 为空则 refresh_all_providers() 自愈后再取
3. `_get_client_for_request()`: 指定 provider/model 不可用或 model 不匹配时,
   回退到 _resolve_available_fallback(), 不再直接返回 None

TDD 流程:
- RED: 以下测试在原代码下应失败 (返回 No client available / _clients 为空)
- GREEN: 修复 multi_model_client.py 后应全部通过

运行方式:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.llm.test_llm_provider_fallback -v
"""

import asyncio
import unittest
from typing import List
from unittest.mock import MagicMock, patch

from neurova.llm.multi_model_client import MultiModelLLMClient, ModelClient


def _reset_singleton():
    """重置 MultiModelLLMClient 单例 (类级 + 模块级)"""
    instance = MultiModelLLMClient._instance
    if instance is not None and hasattr(instance, "_initialized"):
        instance._initialized = False
    MultiModelLLMClient._instance = None
    import neurova.llm.multi_model_client as mmc_module
    mmc_module._multi_model_client = None


def _make_provider(provider_id="test", api_key="", enabled=True, default_model="gpt-4",
                   models=None, priority=0):
    """构造 mock ProviderConfig"""
    provider = MagicMock()
    provider.id = provider_id
    provider.enabled = enabled
    provider.api_key = api_key
    provider.default_model = default_model
    provider.models = models or [default_model]
    provider.name = f"Test Provider {provider_id}"
    provider.priority = priority
    return provider


def _make_mock_provider_manager(providers=None, default_provider=None):
    """构造 mock provider_manager"""
    mock_pm = MagicMock()
    mock_pm.get_default_provider.return_value = default_provider
    mock_pm.list_providers.return_value = providers or []
    mock_pm.get_provider.return_value = default_provider
    return mock_pm


def _fake_create_model_client_that_populates(provider_map):
    """返回一个 fake _create_model_client, 把成功的 model client 塞进 _clients。

    provider_map: {provider_id: ProviderConfig}, 只有 map 中且 api_key 非空的才成功。
    """
    def fake_create_model_client(self, provider, model):
        if not provider.api_key:
            return None
        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(return_value={"content": f"{provider.id}-{model}-ok"})
        mc = ModelClient(mock_llm, provider, model)
        self._clients[f"{provider.id}/{model}"] = mc
        return mc
    return fake_create_model_client


class TestDefaultProviderFallback(unittest.TestCase):
    """场景 A: 默认服务商无 key → _initialize_default_clients() 应回退到有 key 服务商"""

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    def test_falls_back_when_default_provider_has_no_key(self):
        """默认服务商无 key, 但有其他 enabled + keyed 服务商时, 应回退初始化后者"""
        default_no_key = _make_provider(provider_id="sensetime", api_key="",
                                        default_model="deepseek-v4-flash",
                                        priority=20)
        fallback_provider = _make_provider(provider_id="bai", api_key="sk-bai-key",
                                           default_model="deepseek-v4-flash-vision-exp",
                                           priority=10)
        mock_pm = _make_mock_provider_manager(
            providers=[default_no_key, fallback_provider],
            default_provider=default_no_key,
        )
        fake_create = _fake_create_model_client_that_populates({})

        with patch("neurova.llm.multi_model_client.get_provider_manager",
                   return_value=mock_pm), \
             patch.object(MultiModelLLMClient, "_create_model_client", fake_create):
            client = MultiModelLLMClient()

        # 断言: 回退到有 key 的 bai, _clients 非空
        self.assertTrue(len(client._clients) > 0,
                        f"默认服务商无 key 时应回退到有 key 服务商, 但 _clients 为空")
        self.assertEqual(client._current_provider_id, "bai",
                         f"默认服务商无 key 时当前 provider 应回退到 bai, 实际: {client._current_provider_id}")

    def test_no_keyed_provider_leaves_clients_empty_and_error_log(self):
        """没有任何 enabled + keyed 服务商时, 应打 ERROR 并保持 _clients 为空"""
        default_no_key = _make_provider(provider_id="sensetime", api_key="", priority=20)
        other_no_key = _make_provider(provider_id="xiaomi-mimo", api_key="", priority=10)
        mock_pm = _make_mock_provider_manager(
            providers=[default_no_key, other_no_key],
            default_provider=default_no_key,
        )
        fake_create = _fake_create_model_client_that_populates({})

        with patch("neurova.llm.multi_model_client.get_provider_manager",
                   return_value=mock_pm), \
             patch.object(MultiModelLLMClient, "_create_model_client", fake_create), \
             self.assertLogs("neurova.llm.multi_model_client", level="ERROR") as cm:
            client = MultiModelLLMClient()

        # 断言: _clients 为空, 且 ERROR 日志提示无可用 provider
        self.assertEqual(len(client._clients), 0)
        self.assertTrue(
            any("No enabled provider with valid api_key" in r.getMessage() for r in cm.records),
            f"期望 ERROR 'No enabled provider with valid api_key', 实际: "
            f"{[r.getMessage() for r in cm.records]}"
        )


class TestRequestFallback(unittest.TestCase):
    """场景 B/C: _get_client_for_request() 在指定 provider/model 不可用时回退"""

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    def _build_client_with_existing_clients(self, existing_clients, current_provider,
                                            current_model, mock_pm):
        """构造一个已有客户端的实例, 用于直接测试 _get_client_for_request"""
        client = MagicMock()
        client.model = current_model
        client.provider = MagicMock()
        client.provider.id = current_provider
        mc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mc._provider_manager = mock_pm
        mc._clients = existing_clients
        mc._current_provider_id = current_provider
        mc._current_model = current_model
        # 让 get_current_client 能根据 _current_provider_id/_current_model 命中 _clients
        return mc, client

    def test_requested_provider_without_key_falls_back(self):
        """指定 provider_id+model 但该 provider 无 key → 回退到已有的可用客户端"""
        # 已有的可用客户端: bai/deepseek-v4-flash
        available = _make_provider(provider_id="bai", api_key="sk-bai-key",
                                   default_model="deepseek-v4-flash")
        mock_pm = _make_mock_provider_manager(
            providers=[available],
            default_provider=available,
        )
        mock_pm.get_provider.return_value = _make_provider(
            provider_id="sensetime", api_key="", default_model="deepseek-v4-flash")

        mc, client = self._build_client_with_existing_clients(
            existing_clients={"bai/deepseek-v4-flash": ModelClient(
                MagicMock(), available, "deepseek-v4-flash")},
            current_provider="bai", current_model="deepseek-v4-flash",
            mock_pm=mock_pm,
        )

        result = mc._get_client_for_request(model="deepseek-v4-flash", provider_id="sensetime")

        # 断言: 即使请求 sensetime(无 key), 也应回退到 bai 的客户端
        self.assertIsNotNone(result, "指定无 key 的 provider 时应回退到可用客户端, 但返回 None")
        self.assertEqual(result.model, "deepseek-v4-flash")
        self.assertEqual(result.provider.id, "bai")

    def test_requested_model_not_found_falls_back(self):
        """按 model 查找且任一 provider 都不含该 model → 回退到已有可用客户端"""
        available = _make_provider(provider_id="bai", api_key="sk-bai-key",
                                   default_model="deepseek-v4-flash")
        mock_pm = _make_mock_provider_manager(
            providers=[available],
            default_provider=available,
        )
        mc, _client = self._build_client_with_existing_clients(
            existing_clients={"bai/deepseek-v4-flash": ModelClient(
                MagicMock(), available, "deepseek-v4-flash")},
            current_provider="bai", current_model="deepseek-v4-flash",
            mock_pm=mock_pm,
        )

        result = mc._get_client_for_request(model="nonexistent-model")

        self.assertIsNotNone(result, "指定的 model 不存在时应回退到可用客户端, 但返回 None")
        self.assertEqual(result.provider.id, "bai")

    def test_chat_returns_success_after_fallback(self):
        """端到端: chat() 请求无 key 的 provider 时, 回退后应返回成功而非 No client available"""
        available = _make_provider(provider_id="bai", api_key="sk-bai-key",
                                   default_model="deepseek-v4-flash")
        requested_no_key = _make_provider(provider_id="sensetime", api_key="",
                                          default_model="deepseek-v4-flash")
        mock_pm = _make_mock_provider_manager(
            providers=[available, requested_no_key],
            default_provider=available,
        )
        mock_pm.get_provider.return_value = requested_no_key

        # 使用真实 chat(), 先用 fake 创建 client 填充 _clients
        fake_create = _fake_create_model_client_that_populates({})
        with patch("neurova.llm.multi_model_client.get_provider_manager",
                   return_value=mock_pm), \
             patch.object(MultiModelLLMClient, "_create_model_client", fake_create):
            client = MultiModelLLMClient()
            # 让请求指向无 key 的 sensetime
            result = asyncio.new_event_loop().run_until_complete(
                client.chat(
                    [{"role": "user", "content": "hi"}],
                    model="deepseek-v4-flash",
                    provider_id="sensetime",
                )
            )

        self.assertTrue(result.get("success"), f"回退后应返回成功, 但实际: {result}")
        self.assertEqual(result.get("provider"), "bai",
                         f"回退后 provider 应为 bai, 实际: {result.get('provider')}")


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(TestDefaultProviderFallback)
    )
    unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(TestRequestFallback)
    )
