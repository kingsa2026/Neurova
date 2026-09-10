"""BUG AUDIT S-13 回归测试: _on_startup 不得同步阻塞事件循环。

缺陷: app.py `_on_startup` 内同步调用 `_initialize_components(app_state)`
（含 Agent/TTS/ASR 等秒级重初始化），阻塞事件循环。

修复契约: 改为 `await asyncio.to_thread(...)` —— 初始化必须运行在
非事件循环线程上，且 startup 全流程完成后 app state 完成装配。

测试策略: monkeypatch 替换 `_initialize_components` 为记录当前线程的桩,
断言其在工作线程执行（非 asyncio.run 主线程）; 并断言后续 set_app_state
完成（startup 冒烟）。
"""
import asyncio
import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s13_0123456789abc")

import neurova.api.app as app_module
import neurova.api.endpoints as endpoints_pkg
import neurova.collaboration.neurflow.storage as nf_storage_module
import neurova.collaboration.neurflow.triggers as nf_triggers_module
import neurova.evolution.closed_loop as closed_loop_module


class _FakeNfStorage:
    def list_enabled_triggers(self, trigger_type):
        return []

    def get_trigger(self, trigger_id):
        return None


@pytest.fixture()
def fake_app_state():
    return SimpleNamespace(
        config={},
        startup_manager=None,
        health_checker=None,
        provider_manager=None,
        llm_router=None,
        llm_client=None,
        channel_manager=None,
        admin_service=None,
        token_manager=None,
        tts_manager=None,
        audio_engine=None,
        asr_manager=None,
        voice_engines={},
        agents={},
    )


@pytest.fixture()
def isolated_startup(monkeypatch):
    """隔离 _on_startup 的副作用: 只保留被测调用链。"""
    ran_on_threads = []

    def _fake_init(state):
        ran_on_threads.append(threading.get_ident())

    monkeypatch.setattr(app_module, "_initialize_components", _fake_init)
    monkeypatch.setattr(app_module, "_schedule_mcp_bootstrap", lambda state: None)
    monkeypatch.setattr(closed_loop_module, "bootstrap_evolution_persistence", lambda: None)
    monkeypatch.setattr(nf_storage_module, "NeurflowStorage", _FakeNfStorage)
    monkeypatch.setattr(nf_triggers_module, "setup_workflow_triggers", _async_noop)

    set_app_state_calls = []
    monkeypatch.setattr(endpoints_pkg, "set_app_state", lambda state: set_app_state_calls.append(state))
    return ran_on_threads, set_app_state_calls


async def _async_noop(*args, **kwargs):
    return None


class TestStartupInitInWorkerThread:
    def test_initialize_components_runs_off_event_loop(self, isolated_startup, fake_app_state):
        """_initialize_components 必须经 asyncio.to_thread 在工作线程执行"""
        ran_on_threads, _ = isolated_startup
        main_thread = threading.get_ident()

        asyncio.run(app_module._on_startup(fake_app_state))

        assert ran_on_threads, "_initialize_components 未被调用"
        assert ran_on_threads[0] != main_thread, (
            "_initialize_components 仍同步运行在事件循环线程上（S-13 未修复）"
        )

    def test_startup_completes_and_sets_app_state(self, isolated_startup, fake_app_state):
        """初始化移入线程后 startup 全流程仍完整走完（冒烟）"""
        _, set_app_state_calls = isolated_startup

        asyncio.run(app_module._on_startup(fake_app_state))

        assert set_app_state_calls, "startup 未走到 set_app_state 装配步骤"
