# -*- coding: utf-8 -*-
"""N1：OpenAIAdapter.stream_call 真流式契约测试（aiohttp SSE，真 socket）。

红灯期 stream_call 是 R6 的 NotImplementedError 诚实桩，本文件断言真流式
行为即红；真 SSE 实现落地后转绿。基线技法复用 R3 的本地 aiohttp 假服务
（tests/unit/llm/test_triageGateNoFailOpen_S5.py）——真 TCP、真 SSE 分帧，
不碰外网。

覆盖面：
- SSE 增量逐帧产出、拼接还原全文，[DONE] 终止且 DONE 后帧被丢弃；
- 请求体形态（stream=true、model、messages、temperature 透传与 call() 同语义）；
- HTTP 401/500 诚实抛错（与 call() 同姿态），失败流不得产出任何增量；
- 凭据缺失诚实抛错；
- 服务端中途断连：异常诚实暴露，断连前已收增量保留，不静默当正常结束；
- 契约形态：async 生成器可 async-for，基类注解同步为 AsyncGenerator（单一事实源）。
"""

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from neurova.llm.adapters.openai_adapter import OpenAIAdapter
from neurova.llm.interfaces.provider_interface import (
    LLMAbstractProvider,
    Message,
    ProviderConfig,
)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _config(base_url: str) -> ProviderConfig:
    return ProviderConfig(
        api_key="sk-test",
        base_url=base_url,
        model_name="gpt-4o-mini",
        timeout_seconds=5.0,
    )


# SSE 帧里的 UTF-8 字节：你 / 好，世界
_FRAME_NI = b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n'
_FRAME_HAO = (
    b'data: {"choices":[{"delta":{"content":'
    b'"\xe5\xa5\xbd\xef\xbc\x8c\xe4\xb8\x96\xe7\x95\x8c"}}]}\n\n'
)


class _SSEServer:
    """本地 OpenAI 兼容 SSE 假服务：真 TCP、真 SSE 分帧，按 mode 变换行为。"""

    def __init__(self, mode: str = "ok"):
        self.mode = mode
        self.received = []
        self._runner = None
        self.port = 0

    async def _handler(self, request):
        self.received.append(await request.json())
        if self.mode in ("401", "500"):
            status = int(self.mode)
            return web.json_response(
                {"error": {"message": f"forced {status} from fake server"}},
                status=status,
            )

        resp = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await resp.prepare(request)
        if self.mode == "abort":
            await resp.write(_FRAME_NI)
            await asyncio.sleep(0.05)  # 让客户端先读到首帧增量
            request.transport.close()  # 模拟服务端中途断连（chunked 未收尾）
            return resp

        for frame in (
            b": keep-alive\n\n",  # SSE 注释行，必须被忽略
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',  # 无 content 帧
            _FRAME_NI,
            _FRAME_HAO,
            b"data: [DONE]\n\n",
        ):
            await resp.write(frame)
            await asyncio.sleep(0.01)
        try:
            await resp.write(
                b'data: {"choices":[{"delta":{"content":"X"}}]}\n\n'
            )  # DONE 之后不得再被产出
            await resp.write_eof()
        except (ConnectionError, aiohttp.ClientError):
            pass  # 客户端已在 [DONE] 处提前断开属预期
        return resp

    async def start(self):
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()


def testStreamCallYieldsIncrementalDeltasAndStopsAtDone():
    """SSE 增量逐帧产出、拼接还原全文；[DONE] 终止且 DONE 后帧被丢弃。"""
    server = _SSEServer("ok")

    async def _scenario():
        await server.start()
        try:
            adapter = OpenAIAdapter(_config(f"http://127.0.0.1:{server.port}/v1"))
            chunks = []
            async for token in adapter.stream_call([_msg("user", "你好")]):
                chunks.append(token)
            assert chunks == ["你", "好，世界"], f"增量序列不符: {chunks}"
            assert "".join(chunks) == "你好，世界"
            payload = server.received[0]
            assert payload["stream"] is True, "流式请求必须带 stream=true"
            assert payload["model"] == "gpt-4o-mini"
            assert payload["messages"][0]["content"] == "你好"
            # 未显式传 temperature → 落到 ProviderConfig 默认（与 call() 同语义）
            assert payload["temperature"] == 0.7
        finally:
            await server.stop()

    asyncio.run(_scenario())


def testStreamCallPassesExplicitTemperatureThrough():
    """显式 temperature 透传到请求体（与 call() 同语义）。"""
    server = _SSEServer("ok")

    async def _scenario():
        await server.start()
        try:
            adapter = OpenAIAdapter(_config(f"http://127.0.0.1:{server.port}/v1"))
            async for _ in adapter.stream_call([_msg("user", "hi")], temperature=0.2):
                pass
            assert server.received[0]["temperature"] == 0.2
        finally:
            await server.stop()

    asyncio.run(_scenario())


def testStreamCallHonestErrorOnHttp401And500():
    """HTTP 401/500 诚实抛错并携带状态码与服务端信息，失败流不得产出增量。"""
    for mode in ("401", "500"):
        server = _SSEServer(mode)

        async def _scenario():
            await server.start()
            try:
                adapter = OpenAIAdapter(_config(f"http://127.0.0.1:{server.port}/v1"))
                tokens = []
                with pytest.raises(RuntimeError) as excInfo:
                    async for token in adapter.stream_call([_msg("user", "hi")]):
                        tokens.append(token)
                assert tokens == [], "失败流不得产出任何增量"
                message = str(excInfo.value)
                assert f"HTTP {mode}" in message, f"报错未带状态码: {message}"
                assert f"forced {mode}" in message, f"报错未带服务端信息: {message}"
            finally:
                await server.stop()

        asyncio.run(_scenario())


def testStreamCallRaisesOnMissingApiKey():
    """凭据缺失与 call() 同姿态：ValueError 诚实抛出，不伪造空流。"""
    adapter = OpenAIAdapter(ProviderConfig(api_key="", model_name="gpt-4o-mini"))

    async def _scenario():
        with pytest.raises(ValueError):
            async for _ in adapter.stream_call([_msg("user", "hi")]):
                pass

    asyncio.run(_scenario())


def testStreamCallSurfacesMidStreamConnectionDrop():
    """服务端中途断连：异常诚实暴露，断连前已收增量保留，不静默当正常结束。"""
    server = _SSEServer("abort")

    async def _scenario():
        await server.start()
        try:
            adapter = OpenAIAdapter(_config(f"http://127.0.0.1:{server.port}/v1"))
            chunks = []
            with pytest.raises((aiohttp.ClientError, ConnectionError, OSError)):
                async for token in adapter.stream_call([_msg("user", "hi")]):
                    chunks.append(token)
            assert chunks == ["你"], f"断连前应已收到首帧增量: {chunks}"
        finally:
            await server.stop()

    asyncio.run(_scenario())


def testStreamCallIsAsyncGeneratorAndBaseAnnotationAligned():
    """契约形态：async 生成器可 async-for；基类注解为 AsyncGenerator（单一事实源）。"""
    adapter = OpenAIAdapter(_config("http://127.0.0.1:9"))
    gen = adapter.stream_call([_msg("user", "hi")])
    assert hasattr(gen, "__aiter__") and hasattr(gen, "__anext__"), (
        "stream_call 必须返回可 async-for 的异步生成器"
    )
    return_hint = LLMAbstractProvider.stream_call.__annotations__.get("return")
    assert "AsyncGenerator" in str(return_hint), f"基类注解未对齐: {return_hint}"
