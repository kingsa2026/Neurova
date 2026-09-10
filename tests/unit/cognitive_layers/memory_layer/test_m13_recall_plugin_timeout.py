"""M-13 回归测试：插件召回链路的超时防护。

根因：neurova_recall.py
- `_run_coroutine_in_thread` 内 `thread.join(timeout=None)` 永久等待；
- 插件模式 `asyncio.gather(*tasks, return_exceptions=True)` 无超时。
任一插件通道挂起（await 永不返回）即永久阻塞整次召回。

修复后契约：
- gather 层按 recall 链路既有 `timeout_seconds` 超时，未完成通道取消，
  已完成通道的部分结果照常返回（对齐 :840 as_completed(timeout=) 先例）；
- 线程层 join 带模块级兜底超时，超时记 warning 并放弃等待。
"""

import asyncio
import threading

import pytest

from neurova.cognitive_layers.memory_layer.channels.base import ChannelResult
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    NeurovaRecallEngine,
    RecallChannel,
)


class _FakeMeta:
    def __init__(self, name):
        self.name = name
        self.display_name = name
        self.description = ""


class _FastChannel:
    """正常通道：立即返回结果"""

    def __init__(self):
        self.metadata = _FakeMeta("text")

    async def retrieve(self, query, limit=10, weight=1.0, memory_manager=None, **kwargs):
        return [
            ChannelResult(memory_id="m-fast", content="fast-hit", score=0.9, channel="text")
        ]


class _HangingChannel:
    """挂起通道：await 永不返回（模拟插件卡死）"""

    def __init__(self):
        self.metadata = _FakeMeta("category")

    async def retrieve(self, query, limit=10, weight=1.0, memory_manager=None, **kwargs):
        await asyncio.sleep(3600)
        return []


class _FakeRegistry:
    def __init__(self, channels):
        self._channels = channels

    def get_active(self):
        return self._channels


def _make_engine(timeout_seconds=1.0):
    return NeurovaRecallEngine(
        memory_manager=None,
        timeout_seconds=timeout_seconds,
        use_plugins=True,
        registry=_FakeRegistry([_FastChannel(), _HangingChannel()]),
    )


def _run_in_thread_with_guard(func, guard_seconds):
    """在子线程中执行 func，防挂起：超时后测试失败而非卡死套件。"""
    box = {}

    def runner():
        try:
            box["result"] = func()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=guard_seconds)
    return t, box


class TestM13PluginRecallTimeout:
    def test_hanging_channel_does_not_block_partial_results(self):
        """挂起通道不得永久阻塞召回；健康通道的部分结果必须返回。"""
        engine = _make_engine(timeout_seconds=1.0)
        t, box = _run_in_thread_with_guard(
            lambda: engine._phase1_plugin_recall(
                "query", [RecallChannel.TEXT, RecallChannel.CATEGORY], 5
            ),
            guard_seconds=15.0,
        )
        assert not t.is_alive(), "插件召回被挂起通道永久阻塞（M-13 未修复）"
        assert "error" not in box, f"插件召回抛错: {box.get('error')!r}"
        results = box["result"]
        ids = [r.memory_id for r in results]
        assert "m-fast" in ids, f"健康通道的部分结果丢失: {results!r}"

    def test_run_coroutine_in_thread_join_has_timeout(self, monkeypatch):
        """线程层 join 必须有兜底超时，不得永久等待。"""
        from neurova.cognitive_layers.memory_layer import neurova_recall as nr

        monkeypatch.setattr(
            nr, "_COROUTINE_JOIN_TIMEOUT_SECONDS", 0.5, raising=False
        )

        async def hang():
            await asyncio.sleep(3600)

        box = {}

        def runner():
            box["value"] = nr.NeurovaRecallEngine._run_coroutine_in_thread(hang())

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join(timeout=8.0)
        assert not t.is_alive(), "thread.join 永久等待挂起协程（M-13 未修复）"
        assert "value" in box
