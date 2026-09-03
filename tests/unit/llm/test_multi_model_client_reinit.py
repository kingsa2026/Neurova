"""
LLM-1 修复测试：MultiModelLLMClient 首次初始化失败后不可恢复

背景（bug-hunt Phase 3 根因链）：
1. 服务器启动时 pycryptodome 缺失 → api_key AES-GCM 解密失败 → 所有 provider.api_key 为空
2. MultiModelLLMClient.__init__ 调用 _initialize_default_clients()
3. 三重门控 `default_provider and default_provider.enabled and default_provider.api_key` 失败
4. _clients 保持为空字典
5. _initialized = True 已在 _initialize_default_clients() 之前设置（line 87），锁死单例
6. 即使后续 pycryptodome 安装、api_key 可解密，单例不会重新初始化
7. chat() 返回 {"success": False, "error": "No client available"}
8. AgentLLMClient 包装为 "[LLM Error] No client available"

测试目标：
- RED：复现"首次初始化失败后，即使配置修复也无法恢复"的 bug
- GREEN：通过 reset() + chat() 自愈机制修复
"""

import asyncio
import threading
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from neurova.llm.multi_model_client import MultiModelLLMClient, get_multi_model_client


def _reset_singleton():
    """重置 MultiModelLLMClient 单例（类级 + 模块级）"""
    MultiModelLLMClient._instance = None
    import neurova.llm.multi_model_client as mmc_module
    mmc_module._multi_model_client = None


def _make_provider(provider_id="test", api_key="", enabled=True, default_model="gpt-4", models=None):
    """构造 mock ProviderConfig"""
    provider = MagicMock()
    provider.id = provider_id
    provider.enabled = enabled
    provider.api_key = api_key
    provider.default_model = default_model
    provider.models = models or [default_model]
    provider.name = f"Test Provider {provider_id}"
    return provider


def _make_mock_provider_manager(providers=None, default_provider=None):
    """构造 mock provider_manager"""
    mock_pm = MagicMock()
    mock_pm.get_default_provider.return_value = default_provider
    mock_pm.list_providers.return_value = providers or []
    mock_pm.get_provider.return_value = default_provider
    return mock_pm


class TestMultiModelClientReinit:
    """LLM-1: MultiModelLLMClient 首次初始化失败后不可恢复"""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_init_with_empty_api_key_leaves_clients_empty(self):
        """RED: 首次初始化时 api_key 为空 → _clients 为空，_initialized=True

        复现服务器启动时的状态：pycryptodome 缺失导致 api_key 解密失败为空
        """
        provider_no_key = _make_provider(api_key="")
        mock_pm = _make_mock_provider_manager(
            providers=[provider_no_key],
            default_provider=provider_no_key,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):
            client = MultiModelLLMClient()

        # 验证 bug：_clients 为空但 _initialized 已锁死
        assert client._initialized is True, "_initialized 应已设为 True"
        assert len(client._clients) == 0, "_clients 应为空（api_key 为空导致门控失败）"

    def test_reinit_after_config_fix_via_reset(self):
        """RED→GREEN: 首次初始化失败后，配置修复 + reset() 应能重新初始化

        复现 bug：首次初始化时 api_key 为空 → _clients 空 → _initialized=True
        修复 api_key 后调用 reset() → 重新初始化 → _clients 应非空
        """
        # 阶段 1：首次初始化，api_key 为空（模拟 pycryptodome 缺失）
        provider_no_key = _make_provider(api_key="")
        mock_pm_empty = _make_mock_provider_manager(
            providers=[provider_no_key],
            default_provider=provider_no_key,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm_empty):
            client = MultiModelLLMClient()
            assert len(client._clients) == 0, "首次初始化 _clients 应为空"

        # 阶段 2：配置修复，api_key 有了（模拟 pycryptodome 安装后）
        provider_with_key = _make_provider(api_key="sk-fixed-key-12345")
        mock_pm_fixed = _make_mock_provider_manager(
            providers=[provider_with_key],
            default_provider=provider_with_key,
        )

        # 阶段 3：调用 reset() 重置单例（待实现的方法）
        MultiModelLLMClient.reset()

        # 阶段 4：重新获取单例，应重新初始化
        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm_fixed):
            new_client = get_multi_model_client()

        # GREEN 断言：_clients 应非空
        assert len(new_client._clients) > 0, (
            "配置修复 + reset() 后 _clients 应非空，"
            "但实际为空 — 单例未重新初始化（_initialized 锁死）"
        )

    def test_chat_auto_refresh_on_empty_clients(self):
        """RED→GREEN: chat() 检测 _clients 为空时自动 refresh_all_providers()

        复现：服务器运行时 _clients 为空，chat() 直接返回错误
        修复：chat() 在返回 No client available 前，先尝试 refresh_all_providers()
        """
        # 阶段 1：首次初始化，api_key 为空 → _clients 空
        provider_no_key = _make_provider(api_key="")
        mock_pm_empty = _make_mock_provider_manager(
            providers=[provider_no_key],
            default_provider=provider_no_key,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm_empty):
            client = get_multi_model_client()
            assert len(client._clients) == 0, "首次初始化 _clients 应为空"

        # 阶段 2：配置修复 — provider 现在有 api_key
        provider_with_key = _make_provider(api_key="sk-auto-refresh-key")
        mock_pm_fixed = _make_mock_provider_manager(
            providers=[provider_with_key],
            default_provider=provider_with_key,
        )

        # 阶段 3：调用真实 chat()，应自动 refresh 后返回成功
        # mock _create_model_client 避免真实 LLMClient 初始化
        # mock client.client.chat 避免真实 API 调用
        def fake_create_model_client(self, provider, model):
            from neurova.llm.multi_model_client import ModelClient
            mock_llm_client = MagicMock()
            mock_llm_client.chat = MagicMock(return_value={"content": "auto-refreshed-response"})
            mc = ModelClient(mock_llm_client, provider, model)
            self._clients[f"{provider.id}/{model}"] = mc
            return mc

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm_fixed), \
             patch.object(MultiModelLLMClient, "_create_model_client", fake_create_model_client):
            # 更新 client 的 provider_manager 引用（因为 get_multi_model_client 返回的是已初始化的实例）
            client._provider_manager = mock_pm_fixed

            result = asyncio.new_event_loop().run_until_complete(
                client.chat([{"role": "user", "content": "hi"}])
            )

        # GREEN 断言：应返回成功响应，而非 "No client available"
        assert result.get("success") is True, (
            f"chat() 应在 refresh 后返回成功，但实际: {result}"
        )
        assert "response" in result, f"响应应包含 response 字段，但实际: {result}"

    def test_chat_returns_error_when_refresh_also_fails(self):
        """GREEN: chat() 在 refresh 后仍无 client 时，返回 No client available

        确保自愈不会无限重试或掩盖真实错误
        """
        # provider 始终没有 api_key
        provider_no_key = _make_provider(api_key="")
        mock_pm = _make_mock_provider_manager(
            providers=[provider_no_key],
            default_provider=provider_no_key,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):
            client = get_multi_model_client()
            assert len(client._clients) == 0

            result = asyncio.new_event_loop().run_until_complete(
                client.chat([{"role": "user", "content": "hi"}])
            )

        # 验证：refresh 后仍无 client → 返回错误
        assert result.get("success") is False, (
            f"refresh 失败后应返回 success=False，但实际: {result}"
        )
        assert result.get("error") == "No client available", (
            f"应返回 'No client available' 错误，但实际: {result}"
        )

    def test_reset_clears_initialized_flag(self):
        """RED→GREEN: reset() 应清除 _initialized 标志，允许重新初始化"""
        provider = _make_provider(api_key="sk-test")
        mock_pm = _make_mock_provider_manager(
            providers=[provider],
            default_provider=provider,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):
            client = MultiModelLLMClient()
            assert client._initialized is True

        # 调用 reset()
        MultiModelLLMClient.reset()

        # 验证 _instance 被清除
        assert MultiModelLLMClient._instance is None, (
            "reset() 后 _instance 应为 None，允许重新构造"
        )

        # 验证模块级单例也被清除
        import neurova.llm.multi_model_client as mmc_module
        assert mmc_module._multi_model_client is None, (
            "reset() 后 _multi_model_client 模块变量应为 None"
        )

    def test_reset_is_thread_safe(self):
        """RED→GREEN: reset() 在多线程环境下应线程安全"""
        provider = _make_provider(api_key="sk-test")
        mock_pm = _make_mock_provider_manager(
            providers=[provider],
            default_provider=provider,
        )

        with patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):
            # 先创建一个实例
            MultiModelLLMClient()

            # 并发调用 reset() 和构造
            barrier = threading.Barrier(10)
            errors: List[Exception] = []

            def worker():
                try:
                    barrier.wait()
                    MultiModelLLMClient.reset()
                    MultiModelLLMClient()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert len(errors) == 0, f"并发 reset/构造 出现异常: {errors}"
