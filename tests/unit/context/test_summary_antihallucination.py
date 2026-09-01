# -*- coding: utf-8 -*-
"""
P1-b 摘要反幻觉硬校验防回归网（对标 QP beta.5 ContinuationSummary 校验语义）

三道闸：
1. identifier 逐字闸：摘要中出现的高风险标识符（URL/路径/版本号/hash）
   必须逐字出现在证据（chunks + previous_summary）中
2. repair 单次重试：校验失败把违规标识符喂回 repair prompt 再生成一次
3. fail-closed：repair 后仍违规 → 保留 previous_summary（stale 语义），
   绝不让幻觉摘要进入上下文
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
    """按脚本出牌的 llm_call（每次调用弹一个回复）"""
    from neurova.context.summarizing_compressor import SummarizingCompressor

    script = list(replies)
    calls = []

    async def llm_call(prompt):
        calls.append(prompt)
        return script.pop(0)

    return SummarizingCompressor(llm_call=llm_call, timeout_s=5), calls


class TestAntiHallucinationGate:
    @pytest.mark.asyncio
    async def test_faithful_summary_passes(self):
        comp, calls = _make_compressor([
            "用户部署了 https://api.example.com/v2 服务，版本 2.3.1。"
        ])
        chunks = [_mk_chunk("我们把服务部署到了 https://api.example.com/v2，版本 2.3.1")]
        result = await comp.summarize(chunks, previous_summary="")
        assert result and "api.example.com" in result
        assert len(calls) == 1  # 一次通过，无 repair

    @pytest.mark.asyncio
    async def test_hallucinated_url_triggers_repair(self):
        """摘要编造了证据中不存在的 URL → repair 一次 → 正确版本通过"""
        comp, calls = _make_compressor([
            "用户部署了 https://api.evil-example.com/v9 服务",  # 幻觉
            "用户部署了 https://api.example.com/v2 服务",  # repair 后忠实
        ])
        chunks = [_mk_chunk("我们把服务部署到了 https://api.example.com/v2")]
        result = await comp.summarize(chunks, previous_summary="")
        assert result and "api.example.com/v2" in result
        assert "evil-example" not in result
        assert len(calls) == 2  # 触发了 repair
        assert "repair" in calls[1].lower() or "逐字" in calls[1] or "违规" in calls[1]

    @pytest.mark.asyncio
    async def test_repair_still_hallucinating_falls_back(self):
        """repair 后仍幻觉 → fail-closed 保留旧摘要"""
        comp, calls = _make_compressor([
            "服务在 https://evil-a.com 上",   # 幻觉
            "服务在 https://evil-b.com 上",   # repair 仍幻觉
        ])
        chunks = [_mk_chunk("服务部署在 https://good.example.com")]
        result = await comp.summarize(chunks, previous_summary="旧摘要：部署了服务。")
        assert result == "旧摘要：部署了服务。"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_no_previous_and_double_failure_returns_none(self):
        comp, _ = _make_compressor([
            "版本 9.9.9 上线",   # 幻觉（证据只有 1.2.0）
            "版本 8.8.8 上线",   # repair 仍幻觉
        ])
        chunks = [_mk_chunk("服务版本 1.2.0 发布")]
        result = await comp.summarize(chunks, previous_summary="")
        assert result is None  # 宁可无摘要不投毒

    @pytest.mark.asyncio
    async def test_version_number_verbatim_check(self):
        """版本号逐字：摘要写 2.3.2 而证据是 2.3.1 → 幻觉"""
        comp, _ = _make_compressor(["用户升级到了 2.3.2 版本"])
        chunks = [_mk_chunk("当前版本 2.3.1")]
        result = await comp.summarize(chunks, previous_summary="")
        assert result is None or "2.3.2" not in (result or "")

    @pytest.mark.asyncio
    async def test_previous_summary_identifiers_count_as_evidence(self):
        """已有摘要中的标识符也算证据（增量摘要合法复用）"""
        comp, _ = _make_compressor(["继续使用 https://api.example.com/v2 服务"])
        chunks = [_mk_chunk("服务运行正常")]
        result = await comp.summarize(chunks, previous_summary="已知服务地址 https://api.example.com/v2")
        assert result and "api.example.com" in result

    @pytest.mark.asyncio
    async def test_path_identifier_check(self):
        comp, _ = _make_compressor(["配置写入 /etc/neurova/evil.yaml"])
        chunks = [_mk_chunk("配置文件在 /etc/neurova/config.yaml")]
        result = await comp.summarize(chunks, previous_summary="")
        assert result is None or "/etc/neurova/evil.yaml" not in (result or "")


class TestRepairPrompt:
    @pytest.mark.asyncio
    async def test_repair_prompt_lists_violations(self):
        comp, calls = _make_compressor([
            "见 https://x-hallucinated.io",
            "忠实摘要",
        ])
        chunks = [_mk_chunk("参考 https://good.example.com/doc")]
        await comp.summarize(chunks, previous_summary="")
        assert "https://x-hallucinated.io" in calls[1]  # 违规项回喂
        assert "摘要" in calls[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
