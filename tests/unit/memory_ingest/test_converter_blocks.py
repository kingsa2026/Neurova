# -*- coding: utf-8 -*-
"""共享块词表 converters.blocks 的契约测试。

三家转换器都过这一层，所以块型别名一次收齐、三家同享，而不是每家各写一份：
- 调用块四形：toolCall / toolUse / tool_use / functionCall，参数键 arguments 或 input；
- 结果块三形：tool_result / toolResult / <前缀>_tool_result，关联键五形，正文键三形；
- redacted_thinking 是"有推理但是密文"，必须标 opaque，不能和"源里就没推理"混成一类；
- 结果块里还能嵌媒体块（读图工具的结果就是一张图），嵌着的媒体同样要落包。
"""
from collections import Counter

from neurova.memory_ingest.converters.blocks import split_content


def _call(block_type: str, **fields):
    return split_content([dict({"type": block_type, "id": "c1", "name": "read"}, **fields)])


def test_call_block_aliases_all_become_tool_call():
    events, _ = _call("toolCall", arguments={"p": 1})
    assert events[0].kind == "tool_call" and events[0].tool_call_id == "c1"
    for block_type in ("toolUse", "tool_use", "functionCall"):
        got, strays = _call(block_type, input={"p": 1})
        assert got[0].kind == "tool_call", block_type
        assert strays == Counter(), block_type


def test_result_block_aliases_all_link_to_the_call():
    for block_type in ("tool_result", "toolResult", "mcp_tool_result"):
        for id_key in ("id", "tool_use_id", "tool_call_id", "toolUseId", "toolCallId"):
            events, strays = split_content(
                [{"type": block_type, id_key: "c1", "content": "正文"}])
            assert len(events) == 1, (block_type, id_key)
            assert events[0].kind == "tool_result", (block_type, id_key)
            assert events[0].tool_call_id == "c1", (block_type, id_key)


def test_result_body_comes_from_whichever_key_the_source_used():
    for key, value in (("output", "甲"), ("content", "乙"), ("text", "丙")):
        events, _ = split_content([{"type": "tool_result", "id": "c1", key: value}])
        assert events[0].text == value, key


def test_nested_result_blocks_keep_text_and_media():
    class _Sink:
        def resolve(self, block):
            return {"media": "media/aa.png", "digest": "aa", "bytes": 3, "type": "image"}

    events, strays = split_content([{"type": "tool_result", "id": "c1", "content": [
        {"type": "text", "text": "看图"}, {"type": "image", "data": "AAE="}]}], sink=_Sink())

    assert events[0].text == "看图"
    assert events[0].blocks[0]["media"] == "media/aa.png"
    assert strays == Counter()


def test_error_flag_is_carried_as_tool_state():
    ok, _ = split_content([{"type": "tool_result", "id": "c1", "content": "好"}])
    bad, _ = split_content([{"type": "tool_result", "id": "c1", "content": "坏",
                             "is_error": True}])

    assert ok[0].tool_state == "" and bad[0].tool_state == "error"


def test_redacted_thinking_is_opaque_not_absent():
    events, strays = split_content([{"type": "redacted_thinking", "data": "QUJD"},
                                    {"type": "text", "text": "我答"}])

    assert strays == Counter()
    assert events[0].reasoning_state == "opaque" and events[0].reasoning == ""
    assert events[0].text == "我答"


def test_plain_thinking_stays_readable_text():
    events, _ = split_content([{"type": "thinking", "thinking": "先看"},
                               {"type": "text", "text": "我答"}])

    assert events[0].reasoning == "先看" and events[0].reasoning_state == ""
