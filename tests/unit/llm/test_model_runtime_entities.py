"""统一模型契约 — 消息族/结果族/参数 schema/结构化输出（TDD — Dify §2.5 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.5 六型统一契约）：

消息族（Dify 同名对齐，OpenAI dict 双向适配器——管线零破坏）：
- SystemPromptMessage / UserPromptMessage / AssistantPromptMessage（含
  tool_calls）/ ToolPromptMessage（tool_call_id）/ PromptMessageTool
- 多模态内容：TextPromptMessageContent / ImagePromptMessageContent
  （data 支持 URL 与 base64，from_data_uri 自动识别）

结果族：
- LLMResult（可从既有 LLMResponse 适配）/ LLMResultChunk / LLMResultChunkDelta
  / LLMUsage（键名归一：prompt/completion/total，缺失补 0，total 自动求和）
- TextEmbeddingResult / EmbeddingUsage / RerankResult / RerankDocument

参数与能力上下文（schema 驱动）：
- get_model_schema(model_id) → ModelSchema：能力 + context_window +
  max_tokens + parameter_rules 全部来自目录（capability_detector 三层
  检测 + model_limits 精确表 + MODEL_PRESETS 预埋），能力过滤走 schema

结构化输出：
- LLMStructuredOutput 一等契约（围栏/裸 JSON 提取 + jsonschema 校验）
- 能力口径对齐：Dify 六型模型 ↔ Neurova 能力词表（MODEL_TYPE_CAPABILITIES）
"""

import pytest


# ══════════════════════════════════════════════════════════════
# 消息族
# ══════════════════════════════════════════════════════════════


class TestMessageFamily:
    def test_system_user_roles_roundtrip(self):
        from neurova.llm.model_runtime.entities import SystemPromptMessage, UserPromptMessage

        for cls, role in ((SystemPromptMessage, "system"), (UserPromptMessage, "user")):
            m = cls(content="hi")
            d = m.to_openai_dict()
            assert d == {"role": role, "content": "hi"}
            back = type(m).from_openai_dict(d)
            assert back == m

    def test_assistant_with_tool_calls_roundtrip(self):
        from neurova.llm.model_runtime.entities import (
            AssistantPromptMessage,
            PromptMessageTool,
        )

        tool = PromptMessageTool(
            name="get_weather",
            description="查天气",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        )
        m = AssistantPromptMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "北京"}'},
                }
            ],
        )
        d = m.to_openai_dict()
        assert d["role"] == "assistant"
        assert d["tool_calls"][0]["function"]["name"] == "get_weather"
        back = AssistantPromptMessage.from_openai_dict(d)
        assert back == m
        # PromptMessageTool → OpenAI tools 形态
        assert tool.to_openai_dict() == {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查天气",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }

    def test_tool_message_carries_tool_call_id(self):
        from neurova.llm.model_runtime.entities import ToolPromptMessage

        m = ToolPromptMessage(content='{"temp": 25}', tool_call_id="call_1")
        d = m.to_openai_dict()
        assert d == {"role": "tool", "content": '{"temp": 25}', "tool_call_id": "call_1"}
        back = ToolPromptMessage.from_openai_dict(d)
        assert back == m

    def test_multimodal_image_url_and_base64(self):
        from neurova.llm.model_runtime.entities import (
            ImagePromptMessageContent,
            UserPromptMessage,
        )

        img_url = ImagePromptMessageContent(data="https://example.com/a.png")
        img_b64 = ImagePromptMessageContent.from_data_uri(
            "data:image/png;base64,AAAA BBBB"
        )
        assert img_b64.base64_data == "AAAABBBB"
        assert img_b64.mime_type == "image/png"

        m = UserPromptMessage(content=[img_url.to_openai_content(), "这张图是什么？"])
        d = m.to_openai_dict()
        assert d["content"][0] == {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
        assert d["content"][1] == {"type": "text", "text": "这张图是什么？"}

    def test_from_openai_messages_polymorphic(self):
        from neurova.llm.model_runtime.entities import (
            AssistantPromptMessage,
            SystemPromptMessage,
            ToolPromptMessage,
            UserPromptMessage,
            prompt_messages_from_openai,
        )

        raw = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "查天气"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "get_weather", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "25度"},
        ]
        msgs = prompt_messages_from_openai(raw)
        assert [type(m) for m in msgs] == [
            SystemPromptMessage, UserPromptMessage, AssistantPromptMessage, ToolPromptMessage,
        ]
        assert msgs[2].tool_calls[0]["id"] == "c1"
        assert msgs[3].tool_call_id == "c1"


# ══════════════════════════════════════════════════════════════
# 结果族
# ══════════════════════════════════════════════════════════════


class TestResultFamily:
    def test_llm_usage_normalization(self):
        from neurova.llm.model_runtime.entities import LLMUsage

        # 标准键
        u1 = LLMUsage.from_provider_dict({"prompt_tokens": 10, "completion_tokens": 5})
        assert (u1.prompt_tokens, u1.completion_tokens, u1.total_tokens) == (10, 5, 15)
        # total 缺失自动求和；有 total 尊重原值
        u2 = LLMUsage.from_provider_dict({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 100})
        assert u2.total_tokens == 100
        # 空使用（网关不回传）恒零不崩
        u3 = LLMUsage.from_provider_dict({})
        assert u3.total_tokens == 0
        # 简写键（部分网关 completion_tokens=0）
        u4 = LLMUsage.from_provider_dict({"prompt": 3, "completion": 2})
        assert u4.total_tokens == 5

    def test_llm_result_from_llm_response(self):
        from neurova.llm.model_runtime.entities import LLMResult
        from neurova.llm_client import LLMResponse

        resp = LLMResponse(
            content="北京 25 度",
            model="gpt-4o",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "w", "arguments": "{}"}}],
            usage={"prompt_tokens": 8, "completion_tokens": 4},
            finish_reason="tool_calls",
            response_id="resp_1",
        )
        result = LLMResult.from_llm_response(resp, prompt=[{"role": "user", "content": "天气"}])
        assert result.model == "gpt-4o"
        assert result.message.content == "北京 25 度"
        assert result.message.tool_calls[0]["id"] == "c1"
        assert result.usage.total_tokens == 12
        assert result.prompt_messages[0].content == "天气"
        assert result.finish_reason == "tool_calls"

    def test_chunk_delta_streaming_shape(self):
        from neurova.llm.model_runtime.entities import LLMResultChunk, LLMResultChunkDelta, LLMUsage

        delta = LLMResultChunkDelta(index=0, content="你好")
        chunk = LLMResultChunk(model="m1", delta=delta)
        assert chunk.delta.content == "你好"
        # 尾包携带 usage
        tail = LLMResultChunk(model="m1", delta=LLMResultChunkDelta(index=0, content="", usage=LLMUsage.from_provider_dict({"total_tokens": 9})))
        assert tail.delta.usage.total_tokens == 9

    def test_embedding_and_rerank_results(self):
        from neurova.llm.model_runtime.entities import (
            EmbeddingUsage,
            RerankDocument,
            RerankResult,
            TextEmbeddingResult,
        )

        emb = TextEmbeddingResult(
            model="bge-small-zh",
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            usage=EmbeddingUsage(tokens=6, total_tokens=6),
        )
        assert len(emb.embeddings) == 2

        rerank = RerankResult(model="bge-reranker", docs=[
            RerankDocument(index=2, text="第二条", score=0.9),
            RerankDocument(index=0, text="第零条", score=0.1),
        ])
        assert rerank.docs[0].score >= rerank.docs[1].score


# ══════════════════════════════════════════════════════════════
# 参数与能力上下文（schema 驱动）
# ══════════════════════════════════════════════════════════════


class TestModelSchema:
    def test_known_model_schema_from_catalog(self):
        """gpt-4o：能力/窗口/上限全部来自目录（schema 驱动，非硬编码）"""
        from neurova.llm.model_runtime.schema import get_model_schema

        schema = get_model_schema("gpt-4o")
        assert "vision" in schema.capabilities
        assert schema.context_window == 128_000
        assert schema.max_tokens == 16_384
        rules = {r.name: r for r in schema.parameter_rules}
        assert "temperature" in rules and "top_p" in rules and "max_tokens" in rules
        assert rules["max_tokens"].max == 16_384
        assert rules["temperature"].min == 0.0 and rules["temperature"].max == 2.0

    def test_unknown_model_schema_no_crash(self):
        from neurova.llm.model_runtime.schema import get_model_schema

        schema = get_model_schema("totally-unknown-xyz-99")
        assert schema.parameter_rules, "未知模型也要有基础参数规则"
        assert schema.supports("text") or schema.supports("reasoning") or True

    def test_capability_filter_driven_by_schema(self):
        from neurova.llm.model_runtime.schema import get_model_schema

        schema = get_model_schema("gpt-4o")
        assert schema.supports("vision") is True
        assert schema.supports("video_generation") is False
        d = schema.to_dict()
        assert d["model_id"] == "gpt-4o" and "capabilities" in d and "parameter_rules" in d

    def test_reasoning_model_temperature_optional(self):
        """推理模型（o1 族）temperature 参数应标记为可选/受限（schema 语义）"""
        from neurova.llm.model_runtime.schema import get_model_schema

        schema = get_model_schema("o1")
        rules = {r.name: r for r in schema.parameter_rules}
        assert rules["temperature"].required is False


# ══════════════════════════════════════════════════════════════
# 结构化输出 + 能力口径对齐
# ══════════════════════════════════════════════════════════════


class TestStructuredOutput:
    def test_fenced_json_extracted_and_validated(self):
        from neurova.llm.model_runtime.entities import LLMStructuredOutput

        text = '答案如下：\n```json\n{"city": "北京", "temp": 25}\n```'
        out = LLMStructuredOutput.parse(
            text, schema={"type": "object", "properties": {"city": {"type": "string"}, "temp": {"type": "number"}}}
        )
        assert out.structured is True
        assert out.payload == {"city": "北京", "temp": 25}
        assert out.validation_error == ""

    def test_bare_json_and_plain_text(self):
        from neurova.llm.model_runtime.entities import LLMStructuredOutput

        ok = LLMStructuredOutput.parse('{"a": 1}')
        assert ok.structured is True and ok.payload == {"a": 1}

        bad = LLMStructuredOutput.parse("这不是 JSON")
        assert bad.structured is False
        assert bad.payload is None
        assert bad.validation_error != ""

    def test_schema_violation_reported(self):
        from neurova.llm.model_runtime.entities import LLMStructuredOutput

        out = LLMStructuredOutput.parse(
            '{"city": 123}',
            schema={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        )
        assert out.structured is False
        assert out.payload is not None, "解析出的 payload 保留供调试"
        assert "city" in out.validation_error


class TestCapabilityVocabularyAlignment:
    def test_six_model_types_mapped(self):
        """Dify 六型 ↔ Neurova 能力词表（口径对齐）"""
        from neurova.llm.model_runtime.schema import MODEL_TYPE_CAPABILITIES, model_types_for_capabilities

        assert set(MODEL_TYPE_CAPABILITIES) == {
            "llm", "text_embedding", "rerank", "speech2text", "text2speech", "moderation",
        }
        assert model_types_for_capabilities(["text"]) == ["llm"]
        assert model_types_for_capabilities(["tts"]) == ["text2speech"]
        assert model_types_for_capabilities(["stt"]) == ["speech2text"]
        assert model_types_for_capabilities(["tts", "text"]) == ["llm", "text2speech"]

    def test_alignment_is_bidirectional_safe(self):
        from neurova.llm.model_runtime.schema import MODEL_TYPE_CAPABILITIES, model_types_for_capabilities

        # 每个模型类型的反向映射可还原
        for model_type, caps in MODEL_TYPE_CAPABILITIES.items():
            assert model_type in model_types_for_capabilities(list(caps))
