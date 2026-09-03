"""
Auto 路由故障韧性测试（2026-09-03 第三轮）

用户需求：auto 模式下 LLMRouter 增加——
1. 429 退避：指数退避（30s→60s→120s→240s，上限 30min，±jitter），
   不同于 ModelRateLimiter 的固定暂停；
2. 自动切换可用模型：路由时跳过退避中/暂停中的模型，落到下一个匹配能力者；
3. LLM 404（模型下线/改名）重连机制：404 触发重发现（refresh），
   合理间隔防抖（默认 300s 内不重复刷新）。
"""
import time
import unittest
from typing import List
from unittest.mock import MagicMock, patch

from neurova.llm.llm_router import ModelCapability, RequestType, get_llm_router
from neurova.llm.model_rate_limiter import get_shared_limiter, reset_shared_limiter
from neurova.llm.multi_model_client import MultiModelLLMClient, ModelClient


def _reset_singleton():
    instance = MultiModelLLMClient._instance
    if instance is not None and hasattr(instance, "_initialized"):
        instance._initialized = False
    MultiModelLLMClient._instance = None
    import neurova.llm.multi_model_client as mmc_module
    mmc_module._multi_model_client = None


def _make_provider(provider_id="test", api_key="", enabled=True, default_model="gpt-4",
                   models=None, priority=0):
    provider = MagicMock()
    provider.id = provider_id
    provider.enabled = enabled
    provider.api_key = api_key
    provider.default_model = default_model
    provider.models = models or [default_model]
    provider.name = f"Test Provider {provider_id}"
    provider.priority = priority
    provider.model_metadata = {}
    return provider


def _make_llm(exc):
    """该 client 每次调用抛 exc（None=成功返回）。"""
    llm = MagicMock()
    if exc is not None:
        llm.chat = MagicMock(side_effect=exc)
    else:
        llm.chat = MagicMock(return_value={"content": "ok"})
    return llm


class TestExponentialBackoff429(unittest.TestCase):
    """429 指数退避：连续 429 时暂停时长按 2^n 增长，成功后复位。"""

    def setUp(self):
        reset_shared_limiter()
        self.limiter = get_shared_limiter()

    def tearDown(self):
        reset_shared_limiter()

    def test_first_429_uses_base_pause(self):
        self.limiter.report_429("m1")
        remaining = self.limiter.pause_remaining("m1")
        self.assertGreaterEqual(remaining, 15.0)   # 30s ±50% jitter
        self.assertLessEqual(remaining, 45.0)

    def test_consecutive_429_doubles_pause(self):
        self.limiter.report_429("m1")
        self.limiter.report_429("m1")
        remaining = self.limiter.pause_remaining("m1")
        self.assertGreaterEqual(remaining, 30.0)   # 60s ±50%
        self.assertLessEqual(remaining, 90.0)

    def test_fourth_429_quadruples(self):
        for _ in range(4):
            self.limiter.report_429("m1")
        remaining = self.limiter.pause_remaining("m1")
        self.assertGreaterEqual(remaining, 120.0)  # 240s ±50%
        self.assertLessEqual(remaining, 360.0)

    def test_success_resets_backoff(self):
        for _ in range(3):
            self.limiter.report_429("m1")
        self.limiter.report_success("m1")
        self.assertEqual(self.limiter.pause_remaining("m1"), 0.0)
        # 复位后再次 429 从 base 开始
        self.limiter.report_429("m1")
        self.assertLessEqual(self.limiter.pause_remaining("m1"), 45.0)

    def test_pause_capped(self):
        for _ in range(12):
            self.limiter.report_429("m1")
        # 30*2^11 远超上限 → 应封顶（默认 1800s ±50%）
        self.assertLessEqual(self.limiter.pause_remaining("m1"), 2700.0)

    def test_per_model_isolation(self):
        self.limiter.report_429("m1")
        self.limiter.report_429("m1")
        self.assertEqual(self.limiter.pause_remaining("m2"), 0.0)


class TestAutoRouteSkipsUnhealthy(unittest.TestCase):
    """auto 路由跳过退避/暂停中的模型，落到同能力的下一个候选。"""

    def setUp(self):
        reset_shared_limiter()
        import neurova.llm.llm_router as lr
        lr._router_instance = None
        lr.LLMRouter._instance = None
        self.lr = lr
        self.router = get_llm_router()
        self.router.register_provider("prov-a", "Prov A", [
            {"name": "model-x", "capabilities": [ModelCapability.TEXT.value], "priority": 10},
            {"name": "model-y", "capabilities": [ModelCapability.TEXT.value], "priority": 1},
        ])

    def tearDown(self):
        reset_shared_limiter()
        self.lr._router_instance = None
        self.lr.LLMRouter._instance = None

    def test_selects_highest_priority_when_healthy(self):
        result = self.router.select_model(RequestType.CHAT)
        self.assertEqual(result.model, "model-x")

    def test_skips_paused_model(self):
        get_shared_limiter().report_429("model-x")
        result = self.router.select_model(RequestType.CHAT)
        self.assertIsNotNone(result)
        self.assertEqual(result.model, "model-y")

    def test_all_paused_degrades_to_top_rank(self):
        """全部模型暂停中：不返回 None（否则聊天链路直接断），降级返回排序首位，
        由限流器在 acquire 时快速失败——路由选择与限流执行职责分离。"""
        get_shared_limiter().report_429("model-x")
        get_shared_limiter().report_429("model-y")
        result = self.router.select_model(RequestType.CHAT)
        self.assertIsNotNone(result)
        self.assertEqual(result.model, "model-x")  # 降级仍按优先级取首位


class Test404Reconnect(unittest.TestCase):
    """LLM 404（模型下线/改名）→ 合理间隔内触发一次重发现（refresh），防抖。"""

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    def _build_client(self, llm):
        provider = _make_provider(provider_id="p1", api_key="sk-x", default_model="old-model")
        mock_pm = _make_mock_provider_manager_simple(provider)
        client = MultiModelLLMClient.__new__(MultiModelLLMClient)
        # 最小状态注入（绕开 __init__ 的单例/管理器初始化）
        client._clients = {"p1/old-model": ModelClient(llm, provider, "old-model")}
        client._current_provider_id = "p1"
        client._current_model = "old-model"
        client._provider_manager = mock_pm
        client._init_lock = __import__("threading").RLock()
        client._retry_guards = {}
        client._last_404_reconnect = {}
        return client

    def test_404_triggers_refresh_once(self):
        llm = _make_llm(Exception("404 model not found"))
        client = self._build_client(llm)

        with patch.object(client, "_reconnect_provider", wraps=client._reconnect_provider) as rec:
            result = asyncio_run(client.chat([], model="old-model"))
        self.assertFalse(result["success"])
        rec.assert_called_once()   # 404 触发一次重连

    def test_404_refresh_debounced(self):
        """404 防抖：300s 内重复 404 不再刷新。"""
        llm = _make_llm(Exception("Error code: 404 - model unavailable"))
        client = self._build_client(llm)

        with patch.object(client, "_reconnect_provider", wraps=client._reconnect_provider) as rec:
            asyncio_run(client.chat([], model="old-model"))
            asyncio_run(client.chat([], model="old-model"))
            asyncio_run(client.chat([], model="old-model"))
        rec.assert_called_once()

    def test_non_404_error_no_refresh(self):
        llm = _make_llm(Exception("500 internal"))
        client = self._build_client(llm)
        with patch.object(client, "_reconnect_provider", wraps=client._reconnect_provider) as rec:
            asyncio_run(client.chat([], model="old-model"))
        rec.assert_not_called()

    def test_429_no_refresh(self):
        llm = _make_llm(Exception("429 too many requests"))
        client = self._build_client(llm)
        with patch.object(client, "_reconnect_provider", wraps=client._reconnect_provider) as rec:
            asyncio_run(client.chat([], model="old-model"))
        rec.assert_not_called()


# ---------------------------------------------------------------------------
def _make_mock_provider_manager_simple(provider):
    mock_pm = MagicMock()
    mock_pm.get_provider.return_value = provider
    mock_pm.list_providers.return_value = [provider]
    return mock_pm


def asyncio_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) if False else __import__("asyncio").run(coro)


class TestAutoFailoverSwitch(unittest.TestCase):
    """auto（未指定 provider）模式下调用失败 → 自动切换下一可用候选，有界重试。"""

    def setUp(self):
        _reset_singleton()
        reset_shared_limiter()

    def tearDown(self):
        _reset_singleton()
        reset_shared_limiter()

    def _build_two_model_client(self, first_exc):
        """两个模型：model-a 恒抛 first_exc，model-b 正常。"""
        provider = _make_provider(
            provider_id="p1", api_key="sk-x",
            models=["model-a", "model-b"], default_model="model-a",
        )
        mock_pm = _make_mock_provider_manager_simple(provider)

        client = MultiModelLLMClient.__new__(MultiModelLLMClient)
        llm_a = _make_llm(first_exc)
        llm_b = _make_llm(None)
        client._clients = {
            "p1/model-a": ModelClient(llm_a, provider, "model-a"),
            "p1/model-b": ModelClient(llm_b, provider, "model-b"),
        }
        client._current_provider_id = "p1"
        client._current_model = "model-a"
        client._provider_manager = mock_pm
        client._init_lock = __import__("threading").RLock()
        client._retry_guards = {}
        client._last_404_reconnect = {}
        return client

    def test_429_switches_to_next_model(self):
        client = self._build_two_model_client(Exception("429 too many requests"))
        result = asyncio_run(client.chat([{"role": "user", "content": "hi"}]))
        self.assertTrue(result["success"], f"429 后应切换到 model-b 成功: {result}")
        self.assertEqual(result["model"], "model-b")
        # model-a 被标记退避
        self.assertGreater(get_shared_limiter().pause_remaining("model-a"), 0.0)

    def test_404_switches_to_next_model(self):
        client = self._build_two_model_client(Exception("404 model not found"))
        result = asyncio_run(client.chat([{"role": "user", "content": "hi"}]))
        self.assertTrue(result["success"])
        self.assertEqual(result["model"], "model-b")

    def test_switch_is_bounded(self):
        """所有模型都失败 → 返回最后一次错误，不做无界重试。"""
        provider = _make_provider(
            provider_id="p1", api_key="sk-x",
            models=["model-a", "model-b", "model-c"], default_model="model-a",
        )
        client = MultiModelLLMClient.__new__(MultiModelLLMClient)
        llm_bad = _make_llm(Exception("429 rate limited"))
        client._clients = {
            f"p1/m": ModelClient(llm_bad, provider, m)
            for m in ("model-a", "model-b", "model-c")
        }
        client._current_provider_id = "p1"
        client._current_model = "model-a"
        client._provider_manager = _make_mock_provider_manager_simple(provider)
        client._init_lock = __import__("threading").RLock()
        client._retry_guards = {}
        client._last_404_reconnect = {}

        with patch.object(
            MultiModelLLMClient, "_next_failover_client", autospec=True,
            side_effect=lambda self, failed: self._clients.get("p1/model-b"),
        ) as next_mock:
            result = asyncio_run(client.chat([{"role": "user", "content": "hi"}]))
        self.assertFalse(result["success"])
        # model-b 也失败后：_next_failover_client 第二次被调用返回同一 model-b？不会——
        # exclude 会累积，model-b 已在排除集。此处 side_effect 固定返回 model-b 会导致
        # 死循环风险，因此实现必须按"排除集已含全部候选"终止。
        self.assertLessEqual(next_mock.call_count, 3)

    def test_explicit_provider_no_failover(self):
        """显式指定 provider/model：尊重用户选择，失败不静默切换。"""
        client = self._build_two_model_client(Exception("429 too many requests"))
        result = asyncio_run(client.chat([{"role": "user", "content": "hi"}], provider_id="p1", model="model-a"))
        self.assertFalse(result["success"])
