# -*- coding: utf-8 -*-
"""
P2 可选项①：LLM mock 环境注入点防回归网

语义：NEUROVA_LLM_MOCK=1 时，multi_model_client 的 chat/chat_stream 在
**provider 解析之前**返回 canned 响应——无需任何 API Key/网络即可跑通
全链路（e2e/CI/本地演示）。chat 信封与真实路径同形（response 为
LLMResponse：content/usage 齐备）；流式产出 content chunk + done(usage)。

锁定契约：
1. 环境开关生效/关闭两态
2. 无 provider 配置时 mock 仍可用（解析前置）
3. 信封形状与真实路径一致（success/response/duration/model/provider）
"""
import pytest


class TestMockInjectionPoint:
    @pytest.mark.asyncio
    async def test_chat_returns_canned_when_env_set(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_MOCK", "1")
        from neurova.llm.multi_model_client import MultiModelLLMClient

        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)  # 无任何 provider 配置
        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is True
        assert result["provider"] == "mock"
        assert result["model"] == "mock-model"
        resp = result["response"]
        assert "hi" in resp.content or resp.content  # canned 内容
        assert isinstance(resp.usage, dict)

    @pytest.mark.asyncio
    async def test_chat_unaffected_without_env(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_LLM_MOCK", raising=False)
        from neurova.llm.multi_model_client import MultiModelLLMClient

        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mmc._get_client_for_request = lambda model=None, provider_id=None: None  # 桩：无任何 provider
        # 无 provider、无 mock → 走原路径（No client available 信封）
        result = await mmc.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert "No client" in result["error"]

    @pytest.mark.asyncio
    async def test_chat_stream_yields_canned_chunks(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_MOCK", "1")
        from neurova.llm.multi_model_client import MultiModelLLMClient

        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        chunks = [c async for c in mmc.chat_stream([{"role": "user", "content": "hi"}])]

        assert chunks, "流式 mock 必须产出 chunk"
        assert any(c.get("type") == "content" for c in chunks)
        done = chunks[-1]
        assert done.get("type") == "done"
        assert isinstance(done.get("usage"), dict)

    @pytest.mark.asyncio
    async def test_mock_canned_content_echoes_user(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_MOCK", "1")
        from neurova.llm.multi_model_client import MultiModelLLMClient

        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        result = await mmc.chat([{"role": "user", "content": "e2e-probe-12345"}])
        assert "e2e-probe-12345" in result["response"].content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
