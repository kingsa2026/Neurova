"""
P1-1③ 真摘要压缩器 — 红测

SummarizingCompressor（对标 QP scroll ContinuationSummary 语义）：
- 注入式 llm_call（async callable(prompt) -> str），无注入 → None（调用方保留旧摘要）
- 60s 超时 / 异常 → 返回 previous_summary（失败保留旧摘要）
- 成功 → 脱敏后返回新摘要
- prompt 含增量语义（previous_summary 参与拼装）
"""

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.summarizing_compressor import SummarizingCompressor


def _chunks(n=3):
    return [
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=f"第 {i} 轮讨论了部署方案，包含数据库迁移细节",
            metadata={"turn_id": f"turn_{i}"},
        )
        for i in range(1, n + 1)
    ]


class _FakeLLM:
    def __init__(self, response="这是摘要", sleep=0.0, exc=None):
        self.calls = []
        self._response = response
        self._sleep = sleep
        self._exc = exc

    async def __call__(self, prompt: str) -> str:
        import asyncio

        self.calls.append(prompt)
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._exc:
            raise self._exc
        return self._response


class TestSummarizingCompressor:
    @pytest.mark.asyncio
    async def test_no_llm_call_returns_none(self):
        compressor = SummarizingCompressor(llm_call=None)
        assert await compressor.summarize(_chunks()) is None

    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        llm = _FakeLLM("部署讨论摘要：涉及数据库迁移")
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=5)
        result = await compressor.summarize(_chunks())
        assert result == "部署讨论摘要：涉及数据库迁移"

    @pytest.mark.asyncio
    async def test_prompt_contains_chunk_contents_and_previous_summary(self):
        llm = _FakeLLM("s")
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=5)
        await compressor.summarize(_chunks(2), previous_summary="旧摘要：此前讨论了测试")
        prompt = llm.calls[0]
        assert "旧摘要：此前讨论了测试" in prompt  # 增量语义
        assert "第 1 轮讨论了部署方案" in prompt
        assert "turn_1" in prompt  # 轮次标记供摘要定位

    @pytest.mark.asyncio
    async def test_timeout_keeps_previous_summary(self):
        llm = _FakeLLM(sleep=2.0)
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=0.2)
        result = await compressor.summarize(_chunks(), previous_summary="旧摘要")
        assert result == "旧摘要"  # 失败保留旧摘要

    @pytest.mark.asyncio
    async def test_exception_keeps_previous_summary(self):
        llm = _FakeLLM(exc=RuntimeError("llm down"))
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=5)
        result = await compressor.summarize(_chunks(), previous_summary="旧摘要")
        assert result == "旧摘要"

    @pytest.mark.asyncio
    async def test_success_redacts_secrets(self):
        llm = _FakeLLM("摘要：api_key=sk-abcdef123456 用于部署")
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=5)
        result = await compressor.summarize(_chunks())
        assert "sk-abcdef123456" not in result
        assert "api_key=[REDACTED]" in result or "[REDACTED]" in result

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_none(self):
        llm = _FakeLLM("s")
        compressor = SummarizingCompressor(llm_call=llm, timeout_s=5)
        assert await compressor.summarize([]) is None
        assert llm.calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
