# -*- coding: utf-8 -*-
"""R4（参照系 ad 追平批二）：流分片载荷归一（dict/对象双形态单源）。

契约：流分片有两种形态——LLMResponse 样对象（getattr 可取）与 dict
（网关/测试桩直出的裸 dict）。载荷判类（TEXT/REASONING/TOOL_CALLS/
USAGE/STOP）必须走同一份双形态感知逻辑，不再各处手写 getattr。
"""

from types import SimpleNamespace

from neurova.llm.routing.stream_events import (
    StreamEventKind,
    chunkField,
    chunkPayloadKinds,
)


def _obj(content=None, reasoning=None, tool_calls=None, usage=None, finish=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning,
                           tool_calls=tool_calls, usage=usage, finish_reason=finish)


class TestChunkField:
    def test_object_form(self):
        assert chunkField(_obj(content="hi"), "content") == "hi"

    def test_dict_form(self):
        assert chunkField({"type": "content", "content": "a"}, "content") == "a"

    def test_dict_missing_key_returns_default(self):
        assert chunkField({"type": "done"}, "content", default="") == ""

    def test_object_missing_attr_returns_default(self):
        assert chunkField(object(), "content", default="") == ""


class TestChunkPayloadKinds:
    def test_text_chunk(self):
        kinds = chunkPayloadKinds(_obj(content="你"))
        assert StreamEventKind.TEXT in kinds

    def test_dict_text_chunk(self):
        kinds = chunkPayloadKinds({"type": "content", "content": "a"})
        assert StreamEventKind.TEXT in kinds

    def test_reasoning_chunk(self):
        kinds = chunkPayloadKinds(_obj(reasoning="思考中"))
        assert StreamEventKind.REASONING in kinds

    def test_tool_calls_chunk(self):
        kinds = chunkPayloadKinds(_obj(tool_calls=[{"id": "1"}]))
        assert StreamEventKind.TOOL_CALLS in kinds

    def test_usage_only_chunk(self):
        kinds = chunkPayloadKinds(_obj(usage={"prompt_tokens": 1}))
        assert StreamEventKind.USAGE in kinds
        assert StreamEventKind.TEXT not in kinds  # 纯 usage ≠ 文本载荷

    def test_finish_only_chunk(self):
        kinds = chunkPayloadKinds(_obj(finish="stop"))
        assert StreamEventKind.STOP in kinds

    def test_empty_chunk_no_payload(self):
        kinds = chunkPayloadKinds(_obj())
        assert kinds == set()

    def test_empty_dict_no_payload(self):
        assert chunkPayloadKinds({}) == set()
