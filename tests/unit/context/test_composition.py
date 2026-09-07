"""上下文组成实测（neurova.context.composition）单元测试。

覆盖：
- measure_composition 基础实测（消息分桶 / 工具分类 / 总量）
- 快照读写（get_last_composition / reset_composition）
- 命中率：供应商 cached_tokens 优先，否则重复前缀估算，无源为 None
- classify_tool_schema 分类（MCP / 系统 / 技能 / other）
"""

from __future__ import annotations

import pytest

from neurova.context.composition import (
    classify_tool_schema,
    get_last_composition,
    measure_composition,
    reset_composition,
)


@pytest.fixture(autouse=True)
def _isolate_composition():
    """每个用例隔离快照，防跨用例污染。"""
    reset_composition()
    yield
    reset_composition()


def _builtin_tool(name: str = "web_search") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "搜索网页内容" * 10,
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    }


def _mcp_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "mcp__filesystem__read_file",
            "description": "Read a file from the mounted filesystem",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    }


class TestClassifyToolSchema:
    def test_mcp_double_underscore_prefix(self):
        assert classify_tool_schema(_mcp_tool()) == "mcp"

    def test_builtin_whitelist(self):
        # web_search 在 builtin_tools._BUILTIN_SCHEMAS 白名单内
        assert classify_tool_schema(_builtin_tool("web_search")) == "system"

    def test_unknown_name_falls_to_skill(self):
        tool = _builtin_tool("my_custom_skill_tool")
        assert classify_tool_schema(tool) == "skill"

    def test_malformed_tool_is_other(self):
        assert classify_tool_schema({"type": "function"}) == "other"
        assert classify_tool_schema("not-a-dict") == "other"


class TestMeasureComposition:
    def test_basic_measure_and_snapshot(self):
        messages = [
            {"role": "system", "content": "你是智星。" * 20},
            {"role": "user", "content": "帮我查一下今天的天气"},
        ]
        comp = measure_composition("agent_a", messages, [_builtin_tool(), _mcp_tool()])

        # 快照落盘
        assert get_last_composition("agent_a") is comp

        # 消息分桶
        assert comp["messages"]["buckets"]["system"]["count"] == 1
        assert comp["messages"]["buckets"]["system"]["tokens"] > 0
        assert comp["messages"]["buckets"]["user"]["count"] == 1

        # 工具分类计数
        assert comp["tools"]["system"]["count"] == 1
        assert comp["tools"]["mcp"]["count"] == 1
        assert comp["tools"]["skill"]["count"] == 0

        # 总量 = 消息 + 工具
        assert comp["total_tokens"] == comp["messages"]["total_tokens"] + sum(
            v["tokens"] for v in comp["tools"].values()
        )
        assert comp["total_tokens"] > 0

    def test_first_turn_no_hit_rate(self):
        comp = measure_composition("agent_b", [{"role": "user", "content": "hi"}], None)
        assert comp["cache_hit_rate"] is None
        assert comp["cache_source"] == "none"

    def test_second_turn_prefix_hit_rate_high(self):
        # 第二轮 = 第一轮前缀 + 追加消息 → 重复前缀比例应显著大于 0
        turn1 = [
            {"role": "system", "content": "固定系统提示" * 50},
            {"role": "user", "content": "第一问"},
        ]
        measure_composition("agent_c", turn1, None)
        turn2 = [
            {"role": "system", "content": "固定系统提示" * 50},
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
        ]
        comp = measure_composition("agent_c", turn2, None)
        assert comp["cache_source"] == "prefix_estimate"
        assert comp["cache_hit_rate"] is not None
        assert comp["cache_hit_rate"] > 0.3

    def test_provider_cached_tokens_takes_priority(self):
        turn1 = [{"role": "system", "content": "固定" * 100}]
        measure_composition("agent_d", turn1, None)
        turn2 = [{"role": "system", "content": "固定" * 100}, {"role": "user", "content": "问"}]
        comp = measure_composition(
            "agent_d",
            turn2,
            None,
            provider_usage={"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 800}},
        )
        assert comp["cache_source"] == "provider"
        assert comp["cache_hit_rate"] == pytest.approx(0.8)

    def test_provider_zero_prompt_falls_back(self):
        measure_composition("agent_e", [{"role": "system", "content": "x" * 500}], None)
        comp = measure_composition(
            "agent_e",
            [{"role": "system", "content": "x" * 500}, {"role": "user", "content": "y"}],
            None,
            provider_usage={"prompt_tokens": 0, "prompt_tokens_details": {"cached_tokens": 0}},
        )
        # prompt_tokens=0 无法算比例 → 回退前缀估算
        assert comp["cache_source"] == "prefix_estimate"

    def test_multimodal_content_counted(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "这张图里是什么"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
                ],
            }
        ]
        comp = measure_composition("agent_f", messages, None)
        # 文本段 + 图片固定 800 token，总量必须显著大于纯文本
        assert comp["messages"]["buckets"]["user"]["tokens"] > 800

    def test_tool_calls_in_history_counted(self):
        messages = [
            {"role": "user", "content": "查天气"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"天气"}'}}],
            },
        ]
        comp = measure_composition("agent_g", messages, None)
        assert comp["messages"]["buckets"]["assistant"]["tokens"] > 0

    def test_context_window_carried(self):
        comp = measure_composition("agent_h", [{"role": "user", "content": "hi"}], None, context_window=1000000)
        assert comp["context_window"] == 1000000

    def test_get_missing_agent_returns_none(self):
        assert get_last_composition("never_measured") is None

    def test_snapshot_overwritten_per_agent(self):
        measure_composition("agent_x", [{"role": "user", "content": "一"}], None)
        measure_composition("agent_y", [{"role": "user", "content": "二"}], None)
        assert get_last_composition("agent_x")["messages"]["buckets"]["user"]["tokens"] > 0
        assert get_last_composition("agent_y")["messages"]["buckets"]["user"]["tokens"] > 0
        # 互不串档
        assert get_last_composition("agent_x")["agent_id"] == "agent_x"
