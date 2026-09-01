# -*- coding: utf-8 -*-
"""
P3-a factsheet 轻量版防回归网（对标 QP beta.5 Visual Compact 的 factsheet 反幻觉带）

语义：折叠内容生成摘要后，从原始 chunk **确定性提取**高风险精确值
（URL/路径/版本号/hex-hash），以原生文本带附加在摘要尾部——模型后续
引用精确值时可逐字复制，不依赖从摘要转写。

锁定契约：
1. 摘要尾部带 [关键精确值] 段，逐字列出证据中的标识符
2. 无标识符时不附加空段
3. 标识符来自 chunks + previous_summary 全集
4. 脱敏仍生效（密钥形态不出现在 factsheet）
"""
import pytest


def _mk_chunk(content: str, turn_id: int = 1):
    from neurova.context.pool_models import ContextInput, ContextSource

    return ContextInput(
        source=ContextSource.CONVERSATION,
        content=content,
        priority=50,
        metadata={"turn_id": turn_id, "role": "user"},
    )


def _make_compressor(replies):
    from neurova.context.summarizing_compressor import SummarizingCompressor

    script = list(replies)

    async def llm_call(prompt):
        return script.pop(0)

    return SummarizingCompressor(llm_call=llm_call, timeout_s=5)


class TestFactsheet:
    @pytest.mark.asyncio
    async def test_factsheet_appended_with_identifiers(self):
        comp = _make_compressor(["服务已部署并运行。"])
        chunks = [
            _mk_chunk("部署地址 https://api.example.com/v2，版本 2.3.1"),
            _mk_chunk("配置文件位于 /etc/neurova/config.yaml"),
        ]
        result = await comp.summarize(chunks, previous_summary="")

        assert "[关键精确值" in result  # 段标题（含副注）
        assert "https://api.example.com/v2" in result  # 逐字
        assert "/etc/neurova/config.yaml" in result
        assert "2.3.1" in result

    @pytest.mark.asyncio
    async def test_no_identifiers_no_factsheet(self):
        comp = _make_compressor(["用户讨论了通用话题。"])
        chunks = [_mk_chunk("今天天气不错，我们聊了聊天")]
        result = await comp.summarize(chunks, previous_summary="")
        assert "[关键精确值]" not in result

    @pytest.mark.asyncio
    async def test_factsheet_includes_previous_summary_identifiers(self):
        comp = _make_compressor(["继续使用既有服务。"])
        chunks = [_mk_chunk("服务运行正常")]
        result = await comp.summarize(
            chunks, previous_summary="已知地址 https://legacy.example.org/api"
        )
        assert "https://legacy.example.org/api" in result

    @pytest.mark.asyncio
    async def test_secrets_redacted_from_factsheet(self):
        comp = _make_compressor(["密钥已配置。"])
        chunks = [_mk_chunk("使用密钥 sk-abcdef123456 访问 https://api.example.com/v2")]
        result = await comp.summarize(chunks, previous_summary="")
        # URL 在 factsheet 逐字保留；密钥形态被脱敏
        assert "sk-abcdef123456" not in result
        assert "https://api.example.com/v2" in result

    @pytest.mark.asyncio
    async def test_hallucination_gate_still_applies_to_summary_body(self):
        """factsheet 附加不豁免正文校验：正文幻觉仍走 repair/fail-closed"""
        comp = _make_compressor([
            "服务在 https://hallucinated.example.io 上",   # 幻觉
            "服务在 https://hallucinated.example.io 上",   # repair 仍幻觉
        ])
        chunks = [_mk_chunk("部署在 https://real.example.com")]
        result = await comp.summarize(chunks, previous_summary="旧摘要。")
        assert result == "旧摘要。"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
