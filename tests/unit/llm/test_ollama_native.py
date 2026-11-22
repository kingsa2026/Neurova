# -*- coding: utf-8 -*-
"""R9（参照系 ad 追平批三）：ollama 运行面原生分支（兼容优先门控）。

契约：
- /v1/models 探测明确 404（兼容端点未开）→ 运行面落原生 /api/chat；
- 探测 200 → 走既有 OpenAI 兼容路径（行为不变，/api/chat 不被触碰）；
- 探测结果按 base_url 缓存（进程内只探一次）；
- 非 ollama 服务商不受探测分派影响。
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neurova.llm.providers.ollama_native import (
    ollamaCompatAvailable,
    ollamaNativeRoot,
)


class _OllamaStub:
    """mode: native=仅 /api/chat；compat=/v1 全套。记录各路径命中数。"""

    def __init__(self, mode):
        self.mode = mode
        self.hits = {"models": 0, "compat_chat": 0, "native_chat": 0}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer = self.server.stub
                if self.path.endswith("/models"):
                    outer.hits["models"] += 1
                    if outer.mode == "native":
                        self._json(404, {"error": {"message": "not found"}})
                    else:
                        self._json(200, {"data": [{"id": "stub-model"}]})
                else:
                    self._json(404, {"error": {"message": "nf"}})

            def do_POST(self):
                outer = self.server.stub
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                if self.path.endswith("/chat/completions"):
                    outer.hits["compat_chat"] += 1
                    if outer.mode == "native":
                        self._json(404, {"error": {"message": "not found"}})
                        return
                    self._json(200, {
                        "id": "c1",
                        "choices": [{"index": 0, "message": {"role": "assistant",
                                     "content": "compat-ok"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 2, "completion_tokens": 3,
                                  "total_tokens": 5},
                    })
                elif self.path.endswith("/api/chat"):
                    outer.hits["native_chat"] += 1
                    if outer.mode == "native":
                        if outer.stream:
                            self.send_response(200)
                            self.send_header("Content-Type", "application/x-ndjson")
                            self.end_headers()
                            for piece in ("native-", "stream-ok"):
                                line = json.dumps({
                                    "model": "stub-model",
                                    "message": {"role": "assistant", "content": piece},
                                    "done": False,
                                }) + "\n"
                                self.wfile.write(line.encode())
                            tail = json.dumps({
                                "model": "stub-model", "message": {"role": "assistant",
                                                                   "content": ""},
                                "done": True, "prompt_eval_count": 4, "eval_count": 6,
                            }) + "\n"
                            self.wfile.write(tail.encode())
                        else:
                            self._json(200, {
                                "model": "stub-model",
                                "message": {"role": "assistant", "content": "native-ok"},
                                "done": True, "prompt_eval_count": 4, "eval_count": 6,
                            })
                    else:
                        self._json(404, {"error": {"message": "nf"}})
                else:
                    self._json(404, {"error": {"message": "nf"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.stub = self
        self.stream = False
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _ollama_pm(tmp_path, base_url):
    from neurova.llm.provider_manager import LLMProviderManager

    pm = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    pm.add_provider(name="ollama-local", provider="ollama", base_url=base_url,
                    api_key="sk-ollama", models=["stub-model"],
                    default_model="stub-model", priority=20)
    return pm


class TestProbeAndRoot:
    def test_native_root_strips_v1(self):
        assert ollamaNativeRoot("http://h:11434/v1") == "http://h:11434"
        assert ollamaNativeRoot("http://h:11434") == "http://h:11434"
        assert ollamaNativeRoot("http://h:11434/v1/") == "http://h:11434"

    def test_probe_404_means_native(self):
        stub = _OllamaStub("native")
        try:
            assert ollamaCompatAvailable(stub.base_url()) is False
        finally:
            stub.stop()

    def test_probe_200_means_compat(self):
        stub = _OllamaStub("compat")
        try:
            assert ollamaCompatAvailable(stub.base_url()) is True
        finally:
            stub.stop()

    def test_probe_cached_per_base_url(self):
        stub = _OllamaStub("native")
        try:
            assert ollamaCompatAvailable(stub.base_url()) is False
            assert ollamaCompatAvailable(stub.base_url()) is False
            assert stub.hits["models"] == 1
        finally:
            stub.stop()

    def test_probe_error_fails_open_to_compat(self):
        # 连不上的地址：按可用处理（保持既有兼容路径错误语义）
        assert ollamaCompatAvailable("http://127.0.0.1:1/v1", timeout=0.3) is True


class TestRuntimeFallback:
    def test_mmc_chat_falls_back_to_native(self, tmp_path):
        """兼容端点 404 → /api/chat 原生兜底，chat 成功。"""
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.providers.ollama_native import (
            OllamaNativeClient,
            _resetOllamaProbeCache,
        )

        stub = _OllamaStub("native")
        try:
            _resetOllamaProbeCache()
            pm = _ollama_pm(tmp_path, stub.base_url())
            mmc = MultiModelLLMClient(provider_manager=pm)
            result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
            assert result.get("success") is True, result.get("error")
            assert "native-ok" in getattr(result.get("response"), "content", "")
            assert stub.hits["native_chat"] == 1
            # 装配的确实是原生客户端
            mc = mmc._clients["ollama-local/stub-model"]
            assert isinstance(mc.client, OllamaNativeClient)
        finally:
            stub.stop()

    def test_mmc_stream_falls_back_to_native(self, tmp_path):
        """原生 NDJSON 流归一为 LLMResponse 分片，内容完整。"""
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.providers.ollama_native import _resetOllamaProbeCache

        stub = _OllamaStub("native")
        stub.stream = True
        try:
            _resetOllamaProbeCache()
            pm = _ollama_pm(tmp_path, stub.base_url())
            mmc = MultiModelLLMClient(provider_manager=pm)

            async def run():
                out = []
                async for chunk in mmc.chat_stream([{"role": "user", "content": "hi"}]):
                    if not isinstance(chunk, dict):
                        out.append(chunk.content or "")
                return out

            pieces = asyncio.run(run())
            assert "".join(pieces) == "native-stream-ok"
        finally:
            stub.stop()

    def test_mmc_chat_uses_compat_when_available(self, tmp_path):
        """兼容端点在 → 走 /v1/chat/completions，/api/chat 零触碰。"""
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.providers.ollama_native import _resetOllamaProbeCache

        stub = _OllamaStub("compat")
        try:
            _resetOllamaProbeCache()
            pm = _ollama_pm(tmp_path, stub.base_url())
            mmc = MultiModelLLMClient(provider_manager=pm)
            result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
            assert result.get("success") is True, result.get("error")
            assert "compat-ok" in getattr(result.get("response"), "content", "")
            assert stub.hits["compat_chat"] == 1
            assert stub.hits["native_chat"] == 0
        finally:
            stub.stop()

    def test_non_ollama_not_routed_to_native(self, tmp_path):
        """非 ollama 服务商不做原生分派：兼容 404 仍按既有失败语义。"""
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.providers.ollama_native import _resetOllamaProbeCache

        stub = _OllamaStub("native")
        try:
            _resetOllamaProbeCache()
            from neurova.llm.provider_manager import LLMProviderManager

            pm = LLMProviderManager(config={"config_path": str(tmp_path / "p.json")})
            pm.add_provider(name="plain-openai", provider="openai",
                            base_url=stub.base_url(), api_key="sk",
                            models=["stub-model"], default_model="stub-model",
                            priority=20)
            mmc = MultiModelLLMClient(provider_manager=pm)
            result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
            # openai 兼容 404 → 诚实失败（不落 /api/chat）
            assert stub.hits["native_chat"] == 0
            assert result.get("success") is False
        finally:
            stub.stop()
