# -*- coding: utf-8 -*-
"""embedding 引擎的**原生内存**在丢弃引用时必须被显式释放（pipeline-3 的内存天花板）。

## 现场

受保护子集在 CI 上跑到 83% 被 SIGKILL（`Finished, code: 137`）。平台侧上限不是原因：
流水线最长 20h、该 job 声明 `timeout: 90m`，而它死在 28m50s。137 = 128+9，
即进程被信号杀掉——4 核 runner 的内存是 8 GiB（`runner.cpus × 2 GiB`）。

## 根因

`onnxruntime.InferenceSession` 持有的是**原生**内存，不是 Python 对象内存。
两处丢弃引用都没把它还回去：

- `ONNXEmbeddingEngine.shutdown()` 只 `self._ort_session = None`——引用交给 GC，
  而原生 session 直到 GC 真正回收该对象才关闭，时机不可控；
- `reset_embedding_engine()` 直接 `_embedding_engine = None`，**连 `shutdown()` 都不调**，
  旧引擎连同其 session 一起变成不可达的原生内存。

受保护子集是**单进程**跑 7926 档，逐档 reset 的那些用例各留下一个 session，
模型本身约 130MB、加上运行时工作区，累积到 83% 处就把 8 GiB 吃穿。

## 判据

本条钉「丢弃引用 = 释放原生内存」这一契约本身，而非某个用例的读数：
reset 之后，**旧**引擎的 session 必须已被关闭。用可观测替身注入 session，
避免依赖本机是否装了模型权重。
"""
from __future__ import annotations

import asyncio

import neurova.embedding as embeddingModule
from neurova.embedding import _reset_embedding_engine


async def _resetInsideLoop():
    """在一个运行中的事件循环里做重置（异步用例/异步服务隔离的调用形态）。"""
    _reset_embedding_engine()


class _SpySession:
    """可观测的 session 替身：记录关闭动作是否真的发生。"""

    def __init__(self):
        self.closeCalls = 0

    def close(self):
        self.closeCalls += 1


def _engineWithSpySession():
    """真构造装配出来的引擎 + 替身 session（不碰模型权重、不联网）。"""
    engine = embeddingModule.ONNXEmbeddingEngine(auto_download=False)
    spy = _SpySession()
    engine._ort_session = spy
    engine._initialized = True
    engine._backend_type = "onnx"
    return engine, spy


class TestResetReleasesTheOldEngine:
    def test_reset_closesThePreviousSession(self):
        """reset 必须让旧引擎的 session 真的被关闭，而不只是把引用置空。"""
        engine, spy = _engineWithSpySession()
        previous = embeddingModule._embedding_engine
        embeddingModule._embedding_engine = engine
        try:
            _reset_embedding_engine()
        finally:
            embeddingModule._embedding_engine = previous

        assert spy.closeCalls == 1, (
            "reset_embedding_engine() 丢弃旧引擎时没有关闭它的 InferenceSession——"
            "onnxruntime 的 session 持有原生内存，只置引用为 None 交给 GC 不够，"
            "单进程跑 7926 档会一路累积到把 runner 的 8 GiB 吃穿（pipeline-3 的 137）。"
        )

    def test_resetClosesSessionInsideARunningLoop(self):
        """已有事件循环时也必须释放——那里 `asyncio.run()` 抛 RuntimeError，
        协程从不执行、session 也就不释放（泄漏会在异步上下文里原样复发）。"""
        engine, spy = _engineWithSpySession()
        previous = embeddingModule._embedding_engine
        embeddingModule._embedding_engine = engine
        try:
            asyncio.run(_resetInsideLoop())
        finally:
            embeddingModule._embedding_engine = previous

        assert spy.closeCalls == 1, (
            "在运行中的事件循环里调用 reset_embedding_engine() 没能关闭 session——"
            "释放入口必须是同步的，不能依赖 asyncio.run()。"
        )

    def test_resetLeavesNoEngineBehind(self):
        """释放之后单例确实为空（释放不得变成「留一个已关闭的壳」）。"""
        embeddingModule._embedding_engine = _engineWithSpySession()[0]
        _reset_embedding_engine()
        assert embeddingModule._embedding_engine is None


class TestShutdownClosesTheSession:
    def test_shutdown_closesTheOnnxSession(self):
        """shutdown() 必须调用 session 的关闭动作，而不是只置 None。"""
        engine, spy = _engineWithSpySession()

        asyncio.run(engine.shutdown())

        assert spy.closeCalls == 1, (
            "shutdown() 只把 _ort_session 置为 None，没有调用 session.close()——"
            "原生内存要等 GC 回收该对象才释放，长进程里等于不释放。"
        )
        assert engine._ort_session is None

    def test_shutdownSurvivesASessionWithoutClose(self):
        """替身没有 close 时不得把关闭动作本身变成崩溃（fail-soft 的边界）。"""
        engine, _ = _engineWithSpySession()
        engine._ort_session = object()  # 无 close() 的假后端

        asyncio.run(engine.shutdown())

        assert engine._ort_session is None
