# -*- coding: utf-8 -*-
"""LLM 测试套件共享 fixtures。

429 同模型等待重试在 chat()/chat_stream 中引入
真实 10s 级等待——单元测试验证的是决策逻辑而非 wall-clock，统一桩掉
``MultiModelLLMClient._sleep_for_retry``（等待时长/次数契约的显式断言
见 test_chat_stream_429_retry.py，该文件按实例注入自己的记录桩）。
"""
import pytest

import neurova.llm.multi_model_client as _mmc_mod


@pytest.fixture(autouse=True)
def _fast_429_retry_sleep(monkeypatch, tmp_path):
    # 设置页持久化文件隔离：llm 套件不受真实 data/llm_retry_settings.json 影响
    monkeypatch.setenv("NEUROVA_LLM_RETRY_SETTINGS", str(tmp_path / "llm_retry.json"))

    async def _instant_sleep(self, seconds):
        return None

    monkeypatch.setattr(_mmc_mod.MultiModelLLMClient, "_sleep_for_retry", _instant_sleep)
    yield


@pytest.fixture(autouse=True)
def _isolated_llm_singletons():
    """每个用例前后重置 llm 侧全局单例，掐断跨用例状态污染。

    病根（vision 路由"单跑绿、组合跑红"的定责结论）：本目录大量用例以
    `MultiModelLLMClient.__new__(...)` 取**全局单例**后直接改实例属性，甚至
    实例级覆盖 `_get_client_for_request`（如 test_llm_read_timeout_split 的
    gpt-test 桩）且不清理——单例是进程级最后写者赢，后跑的用例
    （TestModelNameResolution 按模型名解析）于是拿到别人留的客户端。
    LLMRouter 同为进程级单例，scope=admin 注册的 provider 也跨用例残留。
    前后各重置一次：前防别的目录先跑留下的态，后防本目录留给别人。
    """
    from neurova.llm.llm_router import LLMRouter

    def _reset():
        _mmc_mod.MultiModelLLMClient._instance = None
        _mmc_mod.MultiModelLLMClient._instances.clear()
        LLMRouter._instance = None
        # 惰性同步的"只同步一次"记录也按用例复位（初值即 {"admin"}）
        import neurova.llm.llm_router as _router_mod

        _router_mod._synced_scopes.clear()
        _router_mod._synced_scopes.add("admin")

    _reset()
    yield
    _reset()
