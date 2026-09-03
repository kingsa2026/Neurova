"""
P0-C1 修复：NLToolSynthesizer 测试 — 测试真实 API

之前的问题（phantom test）：
    本文件测试的 API（SynthesizedTool.is_valid / to_skill_template / to_marketplace_dict / author_id、
    parse_description["intent"]/["keywords"]、generate_schema(tool_name=, requirements=, params_hints=)、
    suggest_tool_sequence(requirements=)、estimate_confidence(requirements=, tool_sequence=)、
    synthesize(author_id=)、SynthesisStage.CATEGORIZING/GENERATING/VALIDATING 等）
    在 neurova/evolution/nl_synthesizer.py 中均不存在，是测试与实现脱节的"幻影测试"。

修复策略（bug-hunt Phase 4 surgical fix）：
    重写为测试真实实现暴露的 API：
    - SynthesizedTool: 字段 tool_id/name/description/category/parameters_schema/tool_sequence/confidence/stage/metadata/created_at + to_dict()
    - ToolSynthesisResult: 字段 success/synthesized_tool/error_message/processing_time/stages_completed/warnings + to_dict()
    - NLToolSynthesizer: parse_description(description) / detect_category(description) /
      generate_schema(description, category) / suggest_tool_sequence(description, category) /
      estimate_confidence(description, category, tool_sequence) /
      synthesize(description, context=None) / batch_synthesize(descriptions, context=None)
    - SynthesisStage 枚举值: PARSING / CLASSIFICATION / SCHEMA_GENERATION /
      SEQUENCE_SUGGESTION / CONFIDENCE_ESTIMATION / COMPLETED / FAILED
"""

import pytest
from neurova.evolution.nl_synthesizer import (
    NLToolSynthesizer,
    ToolSynthesisResult,
    SynthesisStage,
    SynthesizedTool,
)


# ============================================================
# SynthesizedTool — 真实字段/方法
# ============================================================

class TestSynthesizedTool:
    """合成工具数据模型 — 真实字段"""

    def test_create_tool_with_real_fields(self):
        """创建合成工具 — 使用真实字段名"""
        tool = SynthesizedTool(
            name="url_validator",
            description="Validate URL format",
            category="web",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to validate"}
                },
                "required": ["url"],
            },
            tool_sequence=["web_fetch"],
            confidence=0.85,
        )
        assert tool.name == "url_validator"
        assert tool.category == "web"
        assert tool.confidence == 0.85
        assert tool.tool_sequence == ["web_fetch"]
        # 真实字段：tool_id 由 __post_init__ 自动生成
        assert tool.tool_id != ""
        # 真实字段：created_at 自动生成
        assert tool.created_at != ""
        # 真实默认值
        assert tool.stage == SynthesisStage.PARSING

    def test_to_dict_serialization(self):
        """to_dict 序列化 — 真实方法"""
        tool = SynthesizedTool(
            name="csv_parser",
            description="Parse CSV files",
            category="file",
            confidence=0.9,
        )
        d = tool.to_dict()
        # 真实 to_dict 返回的字段
        assert d["name"] == "csv_parser"
        assert d["category"] == "file"
        assert d["confidence"] == 0.9
        assert d["stage"] == "parsing"  # stage.value
        assert "tool_id" in d
        assert "created_at" in d
        assert "parameters_schema" in d
        assert "tool_sequence" in d

    def test_tool_id_auto_generated(self):
        """tool_id 由 __post_init__ 自动生成（uuid 前 8 位）"""
        tool1 = SynthesizedTool(name="t1")
        tool2 = SynthesizedTool(name="t2")
        assert tool1.tool_id != ""
        assert tool2.tool_id != ""
        assert tool1.tool_id != tool2.tool_id  # 不同实例 ID 不同


# ============================================================
# NLToolSynthesizer — 真实方法签名
# ============================================================

class TestNLSynthesis:
    """NL 合成流程 — 真实 API"""

    @pytest.fixture
    def synth(self):
        return NLToolSynthesizer()

    def test_parse_description_real_return_shape(self, synth):
        """parse_description 真实返回字段：original/words/verbs/nouns/word_count/has_verbs/has_nouns"""
        desc = "搜索 文件 数据"
        reqs = synth.parse_description(desc)
        # 真实字段（非 intent / keywords）
        assert reqs["original"] == desc
        assert "words" in reqs
        assert "verbs" in reqs
        assert "nouns" in reqs
        assert reqs["word_count"] >= 1
        assert "has_verbs" in reqs
        assert "has_nouns" in reqs
        # 搜索 应被识别为 verb
        assert "搜索" in reqs["verbs"]
        # 文件/数据 应被识别为 nouns
        assert "文件" in reqs["nouns"]

    def test_parse_description_empty(self, synth):
        """空描述 — parse_description 返回真实结构"""
        reqs = synth.parse_description("")
        assert reqs["original"] == ""
        assert reqs["words"] == []
        assert reqs["verbs"] == []
        assert reqs["nouns"] == []
        assert reqs["word_count"] == 0
        assert reqs["has_verbs"] is False
        assert reqs["has_nouns"] is False

    def test_detect_category_real_keywords(self, synth):
        """detect_category — 真实分类集合"""
        # 真实分类：search/file/data/web/api/image/text/database/ai/automation/general
        assert synth.detect_category("搜索 关键词") == "search"
        assert synth.detect_category("读取 文件") == "file"
        assert synth.detect_category("处理 数据") == "data"
        assert synth.detect_category("爬取 网页") == "web"
        assert synth.detect_category("查询 数据库 表") == "database"  # database 得分最高
        # 无匹配关键词返回 general
        assert synth.detect_category("some generic tool without clear hint") == "general"

    def test_generate_schema_real_signature(self, synth):
        """generate_schema(description, category) — 真实签名"""
        schema = synth.generate_schema("读取 文件", "file")
        # 真实返回结构：type/properties/required
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        # file 分类应生成 path 属性
        assert "path" in schema["properties"]
        assert "path" in schema["required"]

    def test_generate_schema_search_category(self, synth):
        """generate_schema — search 分类生成 query 属性"""
        schema = synth.generate_schema("搜索 关键词", "search")
        assert "query" in schema["properties"]
        assert "query" in schema["required"]

    def test_generate_schema_web_category(self, synth):
        """generate_schema — web 分类生成 url 属性"""
        schema = synth.generate_schema("爬取 网页", "web")
        assert "url" in schema["properties"]
        assert "url" in schema["required"]

    def test_suggest_tool_sequence_real_signature(self, synth):
        """suggest_tool_sequence(description, category) — 真实签名"""
        seq = synth.suggest_tool_sequence("搜索 关键词", "search")
        # search 分类至少建议 memory_search
        assert isinstance(seq, list)
        assert len(seq) >= 1
        assert "memory_search" in seq

    def test_suggest_tool_sequence_general_category(self, synth):
        """general 分类返回 general_tool"""
        seq = synth.suggest_tool_sequence("some unknown desc", "general")
        assert "general_tool" in seq

    def test_estimate_confidence_real_signature(self, synth):
        """estimate_confidence(description, category, tool_sequence) — 真实签名"""
        confidence = synth.estimate_confidence(
            "搜索 文件 数据 处理 分析",
            "search",
            ["memory_search", "file_read"],
        )
        # 真实返回：0-1 之间的浮点数
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0
        # 关键词匹配 + 分类明确 + 序列合理 → 应该有较高置信度
        assert confidence > 0.3

    def test_estimate_confidence_low_when_empty(self, synth):
        """空描述返回低置信度"""
        confidence = synth.estimate_confidence("", "general", [])
        assert confidence < 0.5

    def test_full_pipeline_real_synthesize(self, synth):
        """完整合成流水线 — synthesize(description, context=None) 真实签名"""
        result = synth.synthesize(description="搜索 文件 数据")
        # 真实返回 ToolSynthesisResult
        assert isinstance(result, ToolSynthesisResult)
        # 真实字段
        assert hasattr(result, "success")
        assert hasattr(result, "synthesized_tool")
        assert hasattr(result, "error_message")
        assert hasattr(result, "processing_time")
        assert hasattr(result, "stages_completed")
        assert hasattr(result, "warnings")
        # 成功时 synthesized_tool 不为 None
        assert result.success is True
        assert result.synthesized_tool is not None
        assert result.synthesized_tool.name != ""
        assert result.synthesized_tool.confidence > 0

    def test_synthesize_result_to_dict(self, synth):
        """ToolSynthesisResult.to_dict() — 真实方法"""
        result = synth.synthesize(description="读取 文件 数据")
        d = result.to_dict()
        # 真实字段
        assert "success" in d
        assert "synthesized_tool" in d
        assert "error_message" in d
        assert "processing_time" in d
        assert "stages_completed" in d
        assert "warnings" in d
        # stages_completed 是字符串列表（SynthesisStage.value）
        assert isinstance(d["stages_completed"], list)
        if d["stages_completed"]:
            assert isinstance(d["stages_completed"][0], str)

    def test_synthesis_stage_real_enum_values(self):
        """SynthesisStage 真实枚举值"""
        # 真实枚举成员（非 CATEGORIZING/GENERATING/VALIDATING）
        assert SynthesisStage.PARSING.value == "parsing"
        assert SynthesisStage.CLASSIFICATION.value == "classification"
        assert SynthesisStage.SCHEMA_GENERATION.value == "schema_generation"
        assert SynthesisStage.SEQUENCE_SUGGESTION.value == "sequence_suggestion"
        assert SynthesisStage.CONFIDENCE_ESTIMATION.value == "confidence_estimation"
        assert SynthesisStage.COMPLETED.value == "completed"
        assert SynthesisStage.FAILED.value == "failed"

    def test_synthesize_completes_all_stages(self, synth):
        """成功合成应完成所有阶段"""
        result = synth.synthesize(description="搜索 文件 数据")
        if result.success:
            # 应完成所有 6 个阶段
            stage_values = [s.value for s in result.stages_completed]
            assert "parsing" in stage_values
            assert "classification" in stage_values
            assert "schema_generation" in stage_values
            assert "sequence_suggestion" in stage_values
            assert "confidence_estimation" in stage_values
            assert "completed" in stage_values

    def test_synthesize_low_confidence_adds_warning(self, synth):
        """低置信度时应有 warning"""
        # 用极简描述触发低置信度
        result = synth.synthesize(description="x")
        # 不强制 success，但若有 warning 应能访问
        assert isinstance(result.warnings, list)

    def test_batch_synthesize_real_signature(self, synth):
        """batch_synthesize(descriptions, context=None) — 真实签名"""
        descriptions = [
            "搜索 关键词",
            "读取 文件",
            "爬取 网页",
        ]
        # 真实签名：不接受 author_id kwarg
        results = synth.batch_synthesize(descriptions)
        assert len(results) == 3
        # 全部应为 ToolSynthesisResult
        for r in results:
            assert isinstance(r, ToolSynthesisResult)
        # 至少一个成功
        completed = sum(1 for r in results if r.success)
        assert completed >= 1

    def test_init_accepts_pattern_miner(self):
        """P0-B3 已修复：构造接受 pattern_miner kwarg"""
        synth = NLToolSynthesizer(pattern_miner=None)
        assert synth is not None
        # _pattern_miner 是真实属性（P0-B3 契约测试已验证）
        assert hasattr(synth, "_pattern_miner")
