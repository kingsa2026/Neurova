# -*- coding: utf-8 -*-
"""流内静默必须可见（§6-397 批 H 的 C 票·2026-10-22 default 会话实测）。

事故读数（`logs/server.log` 4921-4937、5030-5042 行）：amd/GLM-5.3-Flash 一轮里
连续出现 `已静默 60s／120s／180s／240s` 四段，随后撞 300s 读超时、**静默重试**——
整个过程只在日志里留痕，前端什么都不知道，用户的体感就是"只有转圈"。

现有看门狗自己就写着不行动的理由（`_warn_stream_silence` docstring）：
"ReadTimeout 只知窗口内零字节，无法区分思考模型经缓冲型网关的健康长静默与上游停滞死流"。
这条判断是对的，所以本批**不改断开策略**（乙案要拿程序猜健康与死流，会系统性误杀长思考），
只把同一份事实**送到用户眼前**：静默跨阈值时除了留 WARNING，再让出一条
`{"stream_status": {...}}` 控制字典（与既有 `retry_status` 同族形状）。

本档钉四件事：
1. 静默跨阈值 ⇒ 让出一条带 provider/model/静默秒数/已收字数的 `stream_status`；
2. 让出事件之后，这一次调用**照常读完、照常走完**（不取消、不截断——取消 `__anext__`
   会撕裂 httpx 流，这是本批的实现硬约束）；
3. 快速流不得误报（反向判据）；
4. 同一件事只剩一处实现：独立的看门狗 task 退役（教义第 7 条），WARNING 文案与
   provider/模型/已收字数的取证字段照旧（既有档钉过它们）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import neurova.llm.multi_model_client as mmc
from neurova.llm.model_rate_limiter import reset_shared_limiter


def _chunk(text=""):
    return SimpleNamespace(
        content=text, reasoning_content=None, usage=None, tool_calls=None, finish_reason=None
    )


def _makeManager(monkeypatch, warnSeconds=0.1):
    reset_shared_limiter()
    monkeypatch.setattr(mmc, "_STREAM_SILENCE_WARN_SECONDS", warnSeconds)
    logs: list[str] = []

    class _Cap:
        def warning(self, msg, *a, **k):
            logs.append(msg % a if a else msg)

        def debug(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    monkeypatch.setattr(mmc, "logger", _Cap())
    manager = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
    manager._provider_manager = None
    manager._clients = {}
    manager._current_provider_id = None
    manager._current_model = None
    return manager, logs


def _attach(manager, fakeStream):
    client = SimpleNamespace(
        client=SimpleNamespace(
            chat_stream_async=fakeStream,
            _compat_include_stream_usage=lambda: True,
        ),
        increment_request=lambda **k: None,
        model="gpt-test",
        provider=SimpleNamespace(id="test-provider"),
    )
    manager._get_client_for_request = lambda model=None, provider_id=None: client


def _collect(manager):
    async def go():
        return [c async for c in manager.chat_stream([{"role": "user", "content": "hi"}])]

    return asyncio.run(go())


class TestSilenceBecomesVisible:
    def testSilenceYieldsStreamStatus(self, monkeypatch):
        manager, _logs = _makeManager(monkeypatch)

        async def fakeStream(messages, **kwargs):
            yield _chunk("a")
            await asyncio.sleep(0.35)  # 跨过几个阈值
            yield _chunk("b")

        _attach(manager, fakeStream)
        items = _collect(manager)
        statuses = [i["stream_status"] for i in items if isinstance(i, dict) and "stream_status" in i]
        assert statuses, f"静默跨阈值没让出任何可见事件：{items!r}"
        first = statuses[0]
        assert first.get("provider") == "test-provider", first
        assert first.get("model") == "gpt-test", first
        assert float(first.get("silent_seconds") or 0) > 0, first
        assert first.get("phase") == "silence", first

    def testRealChunksSurviveTheYield(self, monkeypatch):
        """让出状态事件不得吞掉或打断正文——这条流必须照常走完。"""
        manager, _logs = _makeManager(monkeypatch)

        async def fakeStream(messages, **kwargs):
            yield _chunk("前半")
            await asyncio.sleep(0.35)
            yield _chunk("后半")

        _attach(manager, fakeStream)
        items = _collect(manager)
        texts = [getattr(i, "content", "") for i in items if not isinstance(i, dict)]
        assert texts == ["前半", "后半"], texts

    def testWarningStillRecordedAlongside(self, monkeypatch):
        """留痕不降级：WARNING 照旧含 provider（既有判读与调参都靠它）。"""
        manager, logs = _makeManager(monkeypatch)

        async def fakeStream(messages, **kwargs):
            yield _chunk("a")
            await asyncio.sleep(0.35)
            yield _chunk("b")

        _attach(manager, fakeStream)
        _collect(manager)
        assert any("STREAM_SILENCE" in m and "test-provider" in m for m in logs), logs

    def testFastStreamStaysQuiet(self, monkeypatch):
        """反向判据：健康快速流既不该留痕，也不该让出状态事件。"""
        manager, logs = _makeManager(monkeypatch)

        async def fakeStream(messages, **kwargs):
            yield _chunk("a")
            await asyncio.sleep(0.005)
            yield _chunk("b")

        _attach(manager, fakeStream)
        items = _collect(manager)
        assert not any(isinstance(i, dict) and "stream_status" in i for i in items), items
        assert not any("STREAM_SILENCE" in m for m in logs), logs

    def testOneEventPerThresholdNotPerPoll(self, monkeypatch):
        """每跨一个阈值报一次，不是每个轮询周期刷屏。"""
        manager, _logs = _makeManager(monkeypatch, warnSeconds=0.2)

        async def fakeStream(messages, **kwargs):
            yield _chunk("a")
            await asyncio.sleep(0.5)  # ≈2~3 个阈值
            yield _chunk("b")

        _attach(manager, fakeStream)
        items = _collect(manager)
        statuses = [i for i in items if isinstance(i, dict) and "stream_status" in i]
        assert 1 <= len(statuses) <= 3, f"刷屏或漏报：{len(statuses)} 条"
        seconds = [float(s["stream_status"].get("silent_seconds") or 0) for s in statuses]
        assert seconds == sorted(seconds), f"静默时长应逐条递增：{seconds}"


class TestAbandonmentClosesTheSource:
    """消费方中途放弃这一次调用时，上游流与未完成的读取都要收干净。

    `async for` 时代靠引用计数把底层异步生成器关掉；换成显式迭代器后这一步不再自动
    发生——不收就会把 open 的 httpx 流与 pending task 留给后面的用例（合进程里表现成
    别档的 teardown ERROR，是本仓反复踩过的"谁先跑谁决定结果"形态）。
    """

    def testSourceGeneratorIsClosedWhenConsumerStopsEarly(self, monkeypatch):
        manager, _logs = _makeManager(monkeypatch)
        closed = {"did": False}

        async def fakeStream(messages, **kwargs):
            try:
                yield _chunk("a")
                await asyncio.sleep(0.4)
                yield _chunk("b")
            finally:
                closed["did"] = True

        _attach(manager, fakeStream)

        async def go():
            agen = manager.chat_stream([{"role": "user", "content": "hi"}])
            first = await agen.__anext__()  # 只取一片就放弃
            assert getattr(first, "content", None) == "a"
            await agen.aclose()
            # 断言必须落在**关循环之前**：`asyncio.run` 收尾会调
            # `shutdown_asyncgens()` 替我们把悬挂的异步生成器结掉——放在循环外
            # 测到的是解释器的清理，不是生产代码的清理（恒真判据）
            assert closed["did"], "aclose 之后上游异步生成器仍未被生产代码关闭"

        asyncio.run(go())


class TestSingleImplementation:
    def testStandaloneWatchdogTaskRetired(self):
        """同一件事只剩一处实现：独立看门狗协程退役，判定并入读取循环。

        留两份就会漂移成"某条路径的静默不可见"（教义第 7 条判据：该功能在仓内
        只剩一处实现被消费）。
        """
        assert not hasattr(mmc, "_warn_stream_silence"), (
            "独立看门狗仍在场——它让不出事件，与循环内的判定构成第二份定义"
        )
