# -*- coding: utf-8 -*-
"""死服务连接检查诚实性（审计 3.2-1，2026-11-17）：check_connection 对死服务不得报成功。

锁定契约：
1. ollama/lm_studio：API 探测失败必须上抛（get_available_models 不再回落静态默认清单），
   check_connection 经异常路径如实 success=False——静态清单判活是假成功根因。
2. anthropic：check_connection 必须对 /v1/models 发真实探测——旧实现拿"已知模型"
   静态清单充数，一个网络包都不发就报成功；死端口/错 key 如实失败。
3. /v1/models 正常 200 时探测成功且 models_available 与响应一致（探测真的发出去了）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, patch

import pytest

from neurova.llm.providers.anthropic_provider import AnthropicProvider
from neurova.llm.providers.lm_studio_provider import LMStudioProvider
from neurova.llm.providers.ollama_provider import OllamaProvider

# 本机保留端口上必拒绝的地址：不做任何真实外联
DEAD_PORT = "http://127.0.0.1:9"


def _fetch_raises():
    err = RuntimeError("connection refused")
    err.status_code = None
    return AsyncMock(side_effect=err)


class TestOllamaDeadService:
    def test_api_error_propagates_not_swallowed_to_defaults(self):
        """探测失败必须上抛，不得吞掉后回落静态默认清单。"""
        p = OllamaProvider(provider_id="ollama", base_url=DEAD_PORT)
        with patch.object(p, "_fetch_models_from_api", _fetch_raises()):
            with pytest.raises(RuntimeError):
                asyncio.run(p.get_available_models())

    def test_dead_service_check_connection_fails(self):
        p = OllamaProvider(provider_id="ollama", base_url=DEAD_PORT)
        result = asyncio.run(p.check_connection())
        assert result.success is False, "死服务必须报失败（静态清单判活=假成功）"
        assert result.error, "失败必须带原因"

    def test_real_dead_port_check_connection_fails(self):
        """真 socket 形态：未监听端口连接拒绝 → success=False。"""
        p = OllamaProvider(provider_id="ollama", base_url=DEAD_PORT)
        result = asyncio.run(p.check_connection())
        assert result.success is False


class TestLmStudioDeadService:
    def test_api_error_propagates_not_swallowed_to_defaults(self):
        p = LMStudioProvider(provider_id="lm_studio", base_url=DEAD_PORT)
        with patch.object(p, "_fetch_models_from_api", _fetch_raises()):
            with pytest.raises(RuntimeError):
                asyncio.run(p.get_available_models())

    def test_dead_service_check_connection_fails(self):
        p = LMStudioProvider(provider_id="lm_studio", base_url=DEAD_PORT)
        result = asyncio.run(p.check_connection())
        assert result.success is False, "死服务必须报失败（静态兜底=假成功）"
        assert result.error


class _AnthropicModelsHandler(BaseHTTPRequestHandler):
    """本地假 /v1/models：按脚本返回 200/401，并记录收到的请求路径。"""

    script_status = 200
    hits: list[str] = []

    def do_GET(self):  # noqa: N802（stdlib 回调名固定）
        type(self).hits.append(self.path)
        body = json.dumps(
            {"data": [{"id": "claude-probe-1", "display_name": "Probe Model", "type": "model"}]}
        ).encode()
        self.send_response(type(self).script_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默 stdlib 访问日志
        pass


class TestAnthropicRealProbe:
    @pytest.fixture
    def fake_anthropic_server(self):
        server = HTTPServer(("127.0.0.1", 0), _AnthropicModelsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _AnthropicModelsHandler.hits = []
        _AnthropicModelsHandler.script_status = 200
        yield f"http://127.0.0.1:{server.server_address[1]}"
        server.shutdown()
        server.server_close()

    def test_check_connection_hits_models_endpoint(self, fake_anthropic_server):
        """200 响应 → 成功且 models_available 来自真实响应，探测确实发出。"""
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-test", base_url=fake_anthropic_server)
        result = asyncio.run(p.check_connection())
        assert result.success is True
        assert result.models_available == 1
        assert _AnthropicModelsHandler.hits == ["/v1/models"], "探测必须真实打到 /v1/models"

    def test_check_connection_wrong_key_401_fails(self, fake_anthropic_server):
        """401 → 如实失败（静态清单判活形态下这里恒成功）。"""
        _AnthropicModelsHandler.script_status = 401
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-bad", base_url=fake_anthropic_server)
        result = asyncio.run(p.check_connection())
        assert result.success is False
        assert "401" in (result.error or "")

    def test_dead_service_check_connection_fails(self):
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-test", base_url=DEAD_PORT)
        result = asyncio.run(p.check_connection())
        assert result.success is False, "死服务必须报失败（不发网络包就报成功=假成功）"

    def test_model_connection_dead_service_fails(self):
        """模型级检查同根因（教义第 5 条）：本地构造不触网=假成功，必须真实探测。"""
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-test", base_url=DEAD_PORT)
        result = asyncio.run(p.check_model_connection("claude-probe-1"))
        assert result.success is False

    def test_model_connection_real_list_found(self, fake_anthropic_server):
        """真实清单包含该模型 → 成功（provider_only 形态）。"""
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-test", base_url=fake_anthropic_server)
        result = asyncio.run(p.check_model_connection("claude-probe-1"))
        assert result.success is True

    def test_model_connection_real_list_missing(self, fake_anthropic_server):
        """真实清单不含该模型 → 如实报未找到。"""
        p = AnthropicProvider(provider_id="anthropic", api_key="sk-test", base_url=fake_anthropic_server)
        result = asyncio.run(p.check_model_connection("claude-not-there"))
        assert result.success is False
        assert "not found" in (result.error or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
