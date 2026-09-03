"""
LLM Provider Manager reset 链路测试 (RED→GREEN)

测试目标
========
打通 `MultiModelLLMClient.reset()` → `reset_provider_manager()` → 下次 `get_provider_manager()`
返回新实例的链路,修复 reset 在 provider_manager 处断裂的 bug。

背景
====
- `MultiModelLLMClient.reset()` 已清除自己的三层状态(_instance/_initialized/_multi_model_client)
- 但下次 `get_multi_model_client()` → `__init__` → `get_provider_manager()` 仍返回**旧的**
  `_provider_manager`(已缓存了空 api_key 的 providers)
- reset 链路在 provider_manager 处断裂

修复
====
1. 删除 `LLMProviderManager` 类中未使用的 dead code(`_instance = None` + `_lock = threading.Lock()`)
2. 给 `get_provider_manager()` 加双重检查锁定(参照 `secret_store.get_secret_store()` 模式)
3. 新增 `reset_provider_manager()` 函数,清除 `_provider_manager = None`
4. 修改 `MultiModelLLMClient.reset()`,在清除自己状态后**也调用** `reset_provider_manager()`
   (延迟导入避免循环依赖)

测试用例
========
1. `test_reset_provider_manager_clears_singleton`: reset 后 _provider_manager 变 None
2. `test_get_provider_manager_thread_safe`: 并发首次调用只创建一个实例
3. `test_multi_model_reset_calls_provider_reset`: MultiModelLLMClient.reset() 后,
   get_provider_manager() 返回新实例
4. `test_reset_chain_after_config_fix`: 端到端 — 首次缓存空 api_key,reset 后重新加载,
   api_key 应非空

运行
====
    cd e:/项目/Neurova
    python -m unittest tests.unit.llm.test_provider_manager_reset -v

或直接:
    python tests/unit/llm/test_provider_manager_reset.py
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

# 添加项目根目录到 sys.path(允许直接运行)
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from neurova.llm.provider_manager import (
    LLMProviderManager,
    ProviderConfig,
    get_provider_manager,
    reset_provider_manager,  # GREEN 阶段新增
)
from neurova.llm.multi_model_client import MultiModelLLMClient
import neurova.llm.provider_manager as pm_module
import neurova.llm.multi_model_client as mmc_module


def _reset_all_singletons():
    """清理所有相关单例(测试用)"""
    reset_provider_manager()
    MultiModelLLMClient._instance = None
    mmc_module._multi_model_client = None


class TestProviderManagerReset(unittest.TestCase):
    """LLM Provider Manager reset 链路测试"""

    def setUp(self):
        _reset_all_singletons()

    def tearDown(self):
        _reset_all_singletons()

    # ------------------------------------------------------------------
    # 测试 1:reset_provider_manager() 清除单例
    # ------------------------------------------------------------------
    def test_reset_provider_manager_clears_singleton(self):
        """reset_provider_manager() 应清除模块级 _provider_manager 单例

        RED 期望:reset_provider_manager 不存在 → ImportError
        GREEN 期望:调用后 pm_module._provider_manager 为 None
        """
        # 模拟已存在的单例(避免真实文件 IO)
        fake_pm = MagicMock(spec=LLMProviderManager)
        pm_module._provider_manager = fake_pm
        self.assertIsNotNone(
            pm_module._provider_manager,
            "前置条件:_provider_manager 应已设置",
        )

        # 调用 reset
        reset_provider_manager()

        # 验证已清除
        self.assertIsNone(
            pm_module._provider_manager,
            "reset_provider_manager() 后 _provider_manager 应为 None",
        )

    # ------------------------------------------------------------------
    # 测试 2:get_provider_manager() 线程安全
    # ------------------------------------------------------------------
    def test_get_provider_manager_thread_safe(self):
        """并发首次调用 get_provider_manager() 应只创建一个实例

        使用 threading.Barrier 同步,放大竞态窗口。
        RED 期望:reset_provider_manager 不存在 → ImportError
                 或 get_provider_manager 无锁 → 多个实例
        GREEN 期望:双重检查锁定 → 所有线程得到同一实例
        """
        reset_provider_manager()
        self.assertIsNone(pm_module._provider_manager)

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads
        errors = []

        def worker(idx):
            try:
                # 等所有线程就绪后一起冲入,最大化竞态
                barrier.wait(timeout=5)
                pm = get_provider_manager()
                results[idx] = id(pm)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # 断言无异常
        self.assertEqual(errors, [], f"线程出现异常: {errors}")

        # 断言所有线程得到同一个实例 id
        non_none = [r for r in results if r is not None]
        self.assertEqual(
            len(non_none), num_threads,
            f"某些线程未返回结果: {results}",
        )
        self.assertEqual(
            len(set(non_none)), 1,
            f"并发应返回同一实例 id,实际得到 {len(set(non_none))} 个不同 id: {set(non_none)}",
        )

    # ------------------------------------------------------------------
    # 测试 3:MultiModelLLMClient.reset() 调用 reset_provider_manager()
    # ------------------------------------------------------------------
    def test_multi_model_reset_calls_provider_reset(self):
        """MultiModelLLMClient.reset() 后,get_provider_manager() 应返回新实例

        这是 reset 链路的核心断言:reset 必须穿透到 provider_manager 层。

        RED 期望:reset_provider_manager 不存在 → ImportError
                 或 MultiModelLLMClient.reset() 未调用 → 返回旧实例
        GREEN 期望:reset 后下次 get_provider_manager() 返回新实例
        """
        # 阶段 1:首次创建 provider_manager 单例(真实实例,会读默认配置)
        pm1 = get_provider_manager()
        old_id = id(pm1)
        self.assertIs(pm1, pm_module._provider_manager)

        # 阶段 2:调用 MultiModelLLMClient.reset()
        # 期望它内部调用 reset_provider_manager()
        MultiModelLLMClient.reset()

        # 阶段 3:再次获取 provider_manager
        pm2 = get_provider_manager()
        new_id = id(pm2)

        # GREEN 断言:应为不同实例
        self.assertNotEqual(
            old_id, new_id,
            "MultiModelLLMClient.reset() 应通过 reset_provider_manager() 清除 "
            "_provider_manager,使下次 get_provider_manager() 返回新实例。"
            f"实际 old_id={old_id}, new_id={new_id}",
        )

    # ------------------------------------------------------------------
    # 测试 4:端到端 — 配置修复后 reset 链路打通
    # ------------------------------------------------------------------
    def test_reset_chain_after_config_fix(self):
        """端到端 — 首次 _provider_manager 缓存空 api_key,reset 后重新加载,api_key 应非空

        场景模拟(对应 bug-hunt Phase 3):
        1. 首次初始化:pycryptodome 缺失 → api_key 解密失败为 None
           → MultiModelLLMClient._clients 为空
        2. 配置修复:pycryptodome 安装,api_key 可解密
        3. 调用 MultiModelLLMClient.reset() → 应触发 reset_provider_manager()
        4. 重新 get_multi_model_client() → 新 provider_manager → 新 api_key → _clients 非空

        RED 期望:reset_provider_manager 不存在 → ImportError
                 或 reset 链路未打通 → _clients 仍为空
        GREEN 期望:_clients 非空,api_key 已更新
        """
        # mock _load_config:第一次返回 api_key=None,第二次返回 api_key 非空
        # 避免真实文件 IO,隔离测试
        call_count = [0]

        def patched_load(self):
            call_count[0] += 1
            if call_count[0] == 1:
                # 首次:api_key 为空(模拟解密失败)
                self._providers = {
                    "test": ProviderConfig(
                        id="test",
                        name="Test Provider",
                        provider="openai",
                        base_url="https://api.test.com",
                        api_key=None,
                        default_model="test-model",
                        models=["test-model"],
                    )
                }
            else:
                # 第二次:api_key 非空(模拟修复后)
                self._providers = {
                    "test": ProviderConfig(
                        id="test",
                        name="Test Provider",
                        provider="openai",
                        base_url="https://api.test.com",
                        api_key="sk-fixed-real-key-12345",
                        default_model="test-model",
                        models=["test-model"],
                    )
                }
            self._default_provider_id = "test"

        with patch.object(LLMProviderManager, "_load_config", patched_load):
            # 阶段 1:首次初始化,api_key=None → _clients 应为空
            client1 = MultiModelLLMClient()
            self.assertEqual(
                len(client1._clients), 0,
                "首次初始化 api_key=None,_clients 应为空",
            )

            # 阶段 2:调用 reset 链路
            MultiModelLLMClient.reset()

            # 阶段 3:重新初始化 — 应获得新 provider_manager,api_key 非空
            client2 = MultiModelLLMClient()
            self.assertGreater(
                len(client2._clients), 0,
                "reset 后 api_key 应非空,_clients 应非空。"
                "若为空,说明 reset 未穿透到 provider_manager。",
            )

            # 验证 provider 的 api_key 已更新
            provider = client2._provider_manager.get_provider("test")
            self.assertIsNotNone(provider, "test provider 应存在")
            self.assertEqual(
                provider.api_key, "sk-fixed-real-key-12345",
                "api_key 应已更新为修复后的值",
            )

            # 验证 _load_config 被调用 2 次(两个不同实例)
            self.assertEqual(
                call_count[0], 2,
                "_load_config 应被调用 2 次(首次 + reset 后重新创建),"
                f"实际 {call_count[0]} 次",
            )


def _run_tests():
    """用 TextTestRunner 直接运行,避免 pytest collection hang"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestProviderManagerReset)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(_run_tests())
