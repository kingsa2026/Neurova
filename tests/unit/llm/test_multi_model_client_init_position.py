"""
TDD 测试: MultiModelLLMClient._initialized 提前置位 bug 根治

文件路径: tests/unit/llm/test_multi_model_client_init_position.py

背景:
- neurova/llm/multi_model_client.py:87 的 self._initialized = True
  设置在 _initialize_default_clients() (line 99) 之前
- 首次初始化失败后, _initialized 已为 True
- 下次 __init__ 会因 _initialized=True 直接 return, 永久跳过重试
- 这是 "[LLM Error] No client available" bug 的根因

修复方案:
- 把 self._initialized = True 从 line 87 移到 _initialize_default_clients() 之后
- 仅在 _initialize_default_clients() 成功时置位
- 失败时不置位, 允许下次 __init__ 重试

TDD 流程:
- RED: 验证首次初始化失败时, 下次 __init__ 会重试 (当前 bug 会导致不重试)
- GREEN: 修复后测试通过

运行方式:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.llm.test_multi_model_client_init_position -v
"""

import threading
import unittest
from typing import List
from unittest.mock import MagicMock, patch

from neurova.llm.multi_model_client import MultiModelLLMClient


def _reset_singleton():
    """重置 MultiModelLLMClient 单例 (类级 + 模块级)

    清除 _instance 和 _initialized 标志, 确保每个测试用例从干净状态开始
    """
    instance = MultiModelLLMClient._instance
    if instance is not None and hasattr(instance, "_initialized"):
        instance._initialized = False
    MultiModelLLMClient._instance = None
    import neurova.llm.multi_model_client as mmc_module
    mmc_module._multi_model_client = None


def _make_mock_provider_manager():
    """构造 mock provider_manager 避免真实 LLM 初始化"""
    mock_pm = MagicMock()
    mock_pm.get_default_provider.return_value = None
    mock_pm.list_providers.return_value = []
    return mock_pm


class TestMultiModelClientInitPosition(unittest.TestCase):
    """MultiModelLLMClient._initialized 提前置位 bug 根治测试

    验证点:
    1. 首次 _initialize_default_clients 失败时, _initialized 不应被置位
    2. 下次 __init__ 应重试 (再次调用 _initialize_default_clients)
    3. 正常路径 (无异常) 时 _initialized 应为 True
    """

    def setUp(self):
        """每个测试前重置单例"""
        _reset_singleton()

    def tearDown(self):
        """每个测试后重置单例"""
        _reset_singleton()

    def test_retry_after_init_failure(self):
        """RED: 首次 _initialize_default_clients 抛异常时, 下次 __init__ 应重试

        bug: _initialized=True 在 _initialize_default_clients() 之前设置,
             导致首次失败后下次 __init__ 直接 return, 不重试
        fix: _initialized=True 移到 _initialize_default_clients() 之后,
             仅成功时置位, 失败时允许重试
        """
        call_count = 0
        call_lock = threading.Lock()
        calls: List[int] = []

        def fake_init(self):
            nonlocal call_count
            with call_lock:
                call_count += 1
                calls.append(call_count)
            if call_count == 1:
                # 第一次: 模拟初始化失败 (如 api_key 解密失败、provider 未就绪)
                raise RuntimeError("simulated first init failure")
            # 第二次: 成功
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):

            # 第一次构造: 应抛 RuntimeError (因为 _initialize_default_clients 抛异常)
            with self.assertRaises(RuntimeError):
                MultiModelLLMClient()

            # 验证 _initialized 未被设置 (允许重试)
            instance = MultiModelLLMClient._instance
            self.assertFalse(
                getattr(instance, "_initialized", False),
                "首次初始化失败后 _initialized 不应为 True (应允许重试), "
                "这是 _initialized 提前置位 bug 的根因"
            )

            # 第二次构造: 应重试, _initialize_default_clients 被再次调用
            MultiModelLLMClient()

            # 验证 call_count == 2 (第二次真的进入了初始化路径)
            self.assertEqual(call_count, 2, (
                f"第二次 __init__ 应重试 _initialize_default_clients, "
                f"但 call_count={call_count} (期望 2, 表明因 _initialized=True 跳过了重试)"
            ))

    def test_normal_path_sets_initialized(self):
        """GREEN: 正常路径 (无异常) 时 _initialized 应为 True"""
        def fake_init(self):
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):

            client = MultiModelLLMClient()
            self.assertTrue(
                client._initialized,
                "正常路径 (无异常) 应设置 _initialized=True"
            )

    def test_initialized_not_set_before_init_default_clients(self):
        """RED: 验证 _initialized 不应在 _initialize_default_clients 之前被置位

        通过检查 fake_init 执行时的 _initialized 状态来验证
        bug 时: _initialize_default_clients 执行时 _initialized 已为 True
        fix 后: _initialize_default_clients 执行时 _initialized 仍为 False
        """
        init_flag_snapshot: List[bool] = []

        def fake_init(self):
            # 记录 _initialize_default_clients 执行时 _initialized 的状态
            init_flag_snapshot.append(getattr(self, "_initialized", False))
            self._clients = {}

        mock_pm = _make_mock_provider_manager()
        with patch.object(MultiModelLLMClient, "_initialize_default_clients", fake_init), \
             patch("neurova.llm.multi_model_client.get_provider_manager", return_value=mock_pm):

            MultiModelLLMClient()

            self.assertEqual(len(init_flag_snapshot), 1, "fake_init 应被调用 1 次")
            self.assertFalse(
                init_flag_snapshot[0],
                "_initialize_default_clients 执行时 _initialized 不应为 True "
                "(提前置位是 bug 根因)"
            )


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(TestMultiModelClientInitPosition)
    )
