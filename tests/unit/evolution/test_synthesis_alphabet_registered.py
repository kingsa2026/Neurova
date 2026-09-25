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
    """产物名唯一性的**判据唯一归属**是 `test_synth_tool_name_carries_identity.py`
    （Issue #189 已合入 main，名字携带身份 `tool_id`）。

    本文件不再复述"名字怎么拼"——那是同契约的第二份定义（教义第 6 条）。
    此处只保留一条**与名字拼法无关**的收敛读数：不同描述的两条产物不得同名，
    不论拼法是身份后缀还是描述指纹，这条都必须成立。
    """

    def test_differentDescriptions_doNotCollideOnName(self, synth):
        name_a = synth.synthesize("帮我搜索文件").synthesized_tool.name
        name_b = synth.synthesize("读取配置文件").synthesized_tool.name
        assert name_a != name_b, f"不同描述的产物名互相顶替：{name_a!r} == {name_b!r}"


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
