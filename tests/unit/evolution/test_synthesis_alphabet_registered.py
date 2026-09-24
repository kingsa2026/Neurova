"""T-04：合成器字母表去幻 + 产物名唯一 + 第二份表收口。

事故（2026-09-24 取证）：`NLToolSynthesizer.suggest_tool_sequence` 的字母表
10 个名字里 7 个在全仓注册处为 0（`db_query` / `data_process` / `image_process`
/ `text_process` / `model_predict` / `task_execute` / `api_call`），另有一份
平行的模式库表（`_load_tool_patterns`）与遗传引擎的 `_available_tools` 各持
第三、四份幻名。未知分类还会落到兜底名 `general_tool` —— 该名注册处同样为 0，
却被 `plan_orchestrator` 当占位名用。

`T-03` 打开的入口会把缺口交给合成器，字母表不先修好，新通道就成了幽灵技能的
放大器。故本票先于 T-03。

判据：把校验摘掉 ⇒ 幻名重新出现 ⇒ 必红（见 TestReverseLock）。
"""

from __future__ import annotations

import pytest

from neurova.builtin_tools import get_registered_tool_names
from neurova.evolution.nl_synthesizer import NLToolSynthesizer


@pytest.fixture
def synth():
    return NLToolSynthesizer()


_REGISTERED = frozenset(get_registered_tool_names())

#: 事故点名的幻名（注册处为 0），逐个都在本文件的断言范围内。
_PHANTOM_NAMES = (
    "db_query",
    "data_process",
    "image_process",
    "text_process",
    "model_predict",
    "task_execute",
    "api_call",
    "general_tool",
    "ai_tool",
    "data_analyze",
    "web_scrape",
)


class TestAlphabetIsRegistered:
    def test_synthesizedSequenceToolsAllRegistered(self, synth):
        """逐分类驱动 `suggest_tool_sequence`，产出一律落在注册清单内。"""
        categories = (
            "search", "file", "data", "web", "api", "image",
            "text", "database", "ai", "automation", "unknown_thing",
        )
        descriptions = (
            "搜索 文件 数据 处理 分析 网页 爬取 网络",
            "some unknown description without keywords",
        )
        for category in categories:
            for description in descriptions:
                sequence = synth.suggest_tool_sequence(description, category)
                unregistered = [t for t in sequence if t not in _REGISTERED]
                assert not unregistered, (
                    f"分类 {category!r} 产出未注册工具 {unregistered}：序列={sequence}"
                )

    def test_phantomNames_noLongerReferencedByAnyAlphabet(self):
        """全仓字母表类落点不得再引用幻名（教义第 5 条同根扫荡）。"""
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        for name in _PHANTOM_NAMES:
            proc = subprocess.run(
                ["grep", "-rn", f'"{name}"', "neurova/", "--include=*.py"],
                cwd=str(root), capture_output=True, text=True, timeout=60,
            )
            assert not proc.stdout.strip(), (
                f"幻名 {name!r} 仍被引用：\n{proc.stdout}"
            )


class TestUnknownCategoryFallsToReview:
    def test_unknownCategory_producesEmptySequenceNotGeneralTool(self, synth):
        sequence = synth.suggest_tool_sequence("完全不认识的描述 zzzz", "unknown_thing")
        assert "general_tool" not in sequence, f"未知分类落到兜底幻名：{sequence}"
        assert sequence == [], f"无合法候选时应返回空序列并转人工复核：{sequence}"

    def test_unknownCategory_reachesPendingReview(self, synth):
        """无合法候选 ⇒ 走**既有**置信闸转 `PENDING_REVIEW`，不新开一套拦截口径。"""
        from neurova.evolution.nl_synthesizer import SynthesisStage

        result = synth.synthesize("完全不认识的描述 zzzz")
        assert result.success is False, "没有合法候选却报成功"
        assert result.synthesized_tool is not None, "拦下时必须留下产物供人工复核"
        assert result.synthesized_tool.stage is SynthesisStage.PENDING_REVIEW
        assert result.synthesized_tool.tool_sequence == []
        assert result.warnings, "既有置信闸的 warnings 信息位必须保留（不是第二套闸）"

    def test_unregisteredInjection_isRejectedByAlphabetGate(self, synth, monkeypatch):
        """字母表闸的靶心是"名字不存在"：注入一个幻名 ⇒ 必被点名拦下。"""
        from neurova.evolution import nl_synthesizer as _nl
        from neurova.evolution.nl_synthesizer import SynthesisStage

        monkeypatch.setattr(
            _nl.NLToolSynthesizer,
            "resolveAlphabetCandidates",
            lambda self, category, description: ["db_query", "memory_search"],
        )
        result = synth.synthesize("搜索 文件 数据")
        assert result.success is False
        assert result.synthesized_tool.stage is SynthesisStage.PENDING_REVIEW
        assert "db_query" in (result.error_message or ""), (
            f"拦下必须点名非法项：{result.error_message!r}"
        )
        assert synth.unregistered_alphabet_rejections >= 1, "拦下计数必须可见"


class TestArtifactNameUniqueness:
    def test_differentDescriptions_doNotCollideOnName(self, synth):
        """不同描述必须产出不同名字 —— 原实现里所有未命中关键词的描述都叫
        `general_tool_tool`，注册表按 name 建键，后到者静默顶替先到者。"""
        name_a = synth.synthesize("帮我搜索文件").synthesized_tool.name
        name_b = synth.synthesize("读取配置文件").synthesized_tool.name
        assert name_a != name_b, f"不同描述的产物名互相顶替：{name_a!r} == {name_b!r}"

    def test_sameDescription_isIdempotentNotColliding(self, synth):
        """同描述重复合成落到同一名字：同名即同一身份，注册表不产生覆盖告警。

        取描述指纹而非随机后缀是有意的——随机后缀会让"同一件事重复合成"
        变成产生一堆垃圾技能（每次都是新身份）。
        """
        from neurova.skills.skill_contract import resolve_skill_identity

        first = synth.synthesize("帮我搜索文件")
        second = synth.synthesize("帮我搜索文件")

        assert first.synthesized_tool.name == second.synthesized_tool.name
        assert first.synthesized_tool.tool_id != second.synthesized_tool.tool_id
        assert first.synthesized_tool.name not in _REGISTERED, "产物名撞了内置工具名"

    def test_generatedNameCarriesDescriptionFingerprint(self, synth):
        """名字必须带唯一化后缀（描述指纹），不是纯词干。"""
        import hashlib
        import re

        result = synth.synthesize("帮我搜索文件")
        tool = result.synthesized_tool
        fingerprint = hashlib.sha256(tool.description.encode("utf-8", "replace")).hexdigest()[:8]
        assert fingerprint in tool.name, (
            f"产物名没有描述指纹后缀：name={tool.name!r} fingerprint={fingerprint!r}"
        )
        assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", tool.name)

    def test_generatedNameMatchesOpenAiToolNameRule(self, synth):
        import re

        result = synth.synthesize("帮我搜索文件")
        assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", result.synthesized_tool.name)


class TestSingleSourceAlphabet:
    def test_geneticEngineAlphabetIsRegistered(self):
        """遗传引擎的工具池必须与注册清单同源，不得自带第二份幻名表。"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine

        engine = ToolGeneticEngine(seed=7)
        unregistered = [t for t in engine._available_tools if t not in _REGISTERED]
        assert not unregistered, f"遗传引擎持有未注册工具：{unregistered}"

    def test_alphabetDerivesFromTheRegistryReadPoint(self, synth):
        """字母表只有一个读侧：`builtin_tools.get_registered_tool_names`。

        两侧的候选都必须落在同一次读的返回值里 —— 任何一处自带名字表都会破这条。
        """
        from neurova.evolution.genetic_engine import ToolGeneticEngine

        engine = ToolGeneticEngine(seed=3)
        assert set(engine._available_tools) <= _REGISTERED

        table_names = set()
        for names in synth._category_primitives.values():
            table_names.update(names)
        for pattern in synth._tool_patterns.values():
            table_names.update(pattern["tools"])
        assert table_names <= _REGISTERED, f"分类表/模式库含未注册名：{table_names - _REGISTERED}"


class TestReverseLock:
    def test_removingValidation_letsPhantomsBackIn(self, synth, monkeypatch):
        """反向锁：撤掉存在性校验 ⇒ 幻名重新出现在序列里。"""
        from neurova.evolution import nl_synthesizer as _nl

        monkeypatch.setattr(
            _nl.NLToolSynthesizer,
            "resolveAlphabetCandidates",
            lambda self, category, description: ["db_query"],
        )
        sequence = synth.suggest_tool_sequence("随便", "database")
        assert "db_query" in sequence, f"反向锁不成立：{sequence}"
        assert "db_query" not in _REGISTERED
