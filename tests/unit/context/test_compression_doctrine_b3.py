# -*- coding: utf-8 -*-
"""B3（billion-context 对照改进项）：成文压缩教义。

契约：
1. 教义单源（compression_doctrine）：版本化、五段封闭集合、按序拼装；
2. 覆盖门禁：任何覆盖必须 acknowledge_risk=True，否则拒绝（防静默劣化）；
3. 摘要器默认 prompt 内嵌教义（KEEP/DROP/优先级三类齐备）；
4. 原创性红线：教义文本为本仓自研中文，不含第三方教义的英文原文标记。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.compression_doctrine import (
    DOCTRINE_SECTIONS,
    DOCTRINE_VERSION,
    defaultDoctrine,
    renderDoctrine,
    resolveDoctrine,
)
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.summarizing_compressor import SummarizingCompressor, _DEFAULT_PROMPT_TEMPLATE


class TestDoctrineModule:
    def test_version_and_closed_sections(self):
        assert DOCTRINE_VERSION
        assert set(DOCTRINE_SECTIONS) == set(defaultDoctrine().keys())

    def test_render_joins_in_section_order(self):
        text = renderDoctrine()
        pos = [text.index(section[:12]) for section in defaultDoctrine().values()]
        assert pos == sorted(pos), "段序必须按 DOCTRINE_SECTIONS 固定"

    def test_override_requires_acknowledge_risk(self):
        with pytest.raises(ValueError):
            resolveDoctrine({"keep": "自定义保留规则"})
        merged = resolveDoctrine({"keep": "自定义保留规则"}, acknowledge_risk=True)
        assert merged["keep"] == "自定义保留规则"
        assert merged["drop"] == defaultDoctrine()["drop"], "未覆盖段不受影响"

    def test_bad_overrides_dropped_silently(self):
        merged = resolveDoctrine({"keep": 123, "unknown": "x"}, acknowledge_risk=True)
        assert merged["keep"] == defaultDoctrine()["keep"]
        assert "unknown" not in merged


class TestDoctrineContent:
    def test_keep_classes_present(self):
        text = renderDoctrine()
        for marker in ("路径与行号", "签名", "错误信息与堆栈", "决策及其理由", "精确值", "用户意图", "目标及其演变", "开放事项", "引用锚点"):
            assert marker in text, f"KEEP 类缺 {marker}"

    def test_drop_and_priority_present(self):
        text = renderDoctrine()
        for marker in ("冗长日志", "死路探索", "优先级"):
            assert marker in text
        assert "1. 用户总目标" in text and "5. 教训" in text

    def test_originality_no_thirdparty_english_markers(self):
        """原创性红线：不得出现第三方教义的英文原文标记。"""
        text = renderDoctrine()
        for marker in ("KEEP VERBATIM", "Open objectives:", "MEDIA REFS", "TIER 2 COMPRESSION"):
            assert marker not in text


class TestSummarizerEmbedsDoctrine:
    def test_default_prompt_contains_doctrine(self):
        assert "压缩哲学" in _DEFAULT_PROMPT_TEMPLATE
        assert "必须逐字保留" in _DEFAULT_PROMPT_TEMPLATE
        assert "优先级" in _DEFAULT_PROMPT_TEMPLATE

    @pytest.mark.asyncio
    async def test_runtime_prompt_carries_doctrine(self):
        captured = []

        async def llm_call(prompt: str) -> str:
            captured.append(prompt)
            return "摘要正文"

        compressor = SummarizingCompressor(llm_call)
        await compressor.summarize(
            [ContextInput(source=ContextSource.CONVERSATION, content="第 1 轮讨论了部署方案", metadata={"turn_id": "turn_1"})],
            previous_summary="旧摘要",
        )
        assert captured and "必须逐字保留" in captured[0]
