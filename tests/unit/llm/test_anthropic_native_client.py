"""AnthropicNativeClient 单元测试：请求体组装 + thinking 映射 + 接口鸭子兼容"""
import pytest

from neurova.llm.providers.anthropic_client import (
    AnthropicNativeClient,
    anthropic_endpoint_url,
    build_anthropic_body,
)
from neurova.llm_client import LLMConfig


class TestBodyBuilder:
    def test_system_extracted_and_tool_turn_becomes_tool_result(self):
        """§6-76 修法 A 后本条的口径改了：`role=="tool"` **不再被丢弃**。

        改前这条判据钉的是"工具消息应被丢弃"（`if role in ("user","assistant")`），
        而那条过滤正是原生 claude 函数调用失效的成因之一——它当时被 `AnthropicLoop`
        自带的转换掩盖着（环转完把块交给这里 `str()` 拍平，等于把缺陷也一起拍进了
        请求体）。转换收口到本层之后，只有"tool 结果挂到 user 轮"这一种正确形态。
        """
        body = build_anthropic_body(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "hi"},
                {"role": "tool", "tool_call_id": "call_9", "content": "工具正文"},
                {"role": "assistant", "content": "previous"},
            ],
            model="claude-sonnet-4",
        )
        assert body["system"] == "你是助手"
        assert [m["role"] for m in body["messages"]] == ["user", "user", "assistant"]
        result = body["messages"][1]["content"][0]
        assert result["type"] == "tool_result" and result["tool_use_id"] == "call_9"
        assert body["messages"][2]["content"] == [{"type": "text", "text": "previous"}]
        assert body["max_tokens"] > 0
        assert "thinking" not in body

    def test_thinking_effort_maps_budget(self):
        deep = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="deep")
        assert deep["thinking"] == {"type": "enabled", "budget_tokens": 16384}
        assert deep["temperature"] == 1
        assert deep["max_tokens"] > 16384

        std = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="standard")
        assert std["thinking"]["budget_tokens"] == 4096

    def test_light_no_thinking(self):
        body = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="light")
        assert "thinking" not in body


class TestToolConversationReachesTheWire:
    """§6-76 修法 A：协议转换的**唯一落点**是这里，不是 Agent 环。

    改前两处各转一遍（`AnthropicLoop._convert_*` 与 `build_anthropic_body`），而本函数
    对消息只做 `str(content)` 且 `if role in ("user","assistant")`——于是
    `role == "tool"` 与 `assistant.tool_calls` 在路由层**整条消失**。环内那份转换因此
    是承重的：只删不搬，原生 claude 的函数调用会静默退化成纯文本。
    本类钉的就是"搬过来"这件事，形状按 Anthropic 官方要求：tool_use 在 assistant 块里、
    tool_result 在紧随其后的 user 块里、连续的多个结果合进同一条 user。
    """

    def test_tool_call_and_result_survive_as_content_blocks(self):
        body = build_anthropic_body(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "搜索文件"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q": "x"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": '{"found": true}'},
            ],
            model="claude-sonnet-4",
        )

        assert body["system"] == "你是助手"
        assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"], (
            f"工具轮在请求体里被丢掉：{body['messages']}"
        )

        use = body["messages"][1]["content"]
        assert [b["type"] for b in use] == ["tool_use"]
        assert use[0]["id"] == "call_1" and use[0]["name"] == "search"
        assert use[0]["input"] == {"q": "x"}, "arguments 是 JSON 串，得交结构而不是字符串"

        result = body["messages"][2]["content"]
        assert result[0]["type"] == "tool_result"
        assert result[0]["tool_use_id"] == "call_1"
        assert result[0]["content"] == '{"found": true}'

    def test_consecutive_results_merge_into_one_user_turn(self):
        """Anthropic 要求同批多个 tool_result 落在**同一条** user 消息里。"""
        body = build_anthropic_body(
            [
                {"role": "user", "content": "两个都查"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "a", "type": "function", "function": {"name": "s", "arguments": "{}"}},
                        {"id": "b", "type": "function", "function": {"name": "s", "arguments": "{}"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "a", "content": "1"},
                {"role": "tool", "tool_call_id": "b", "content": "2"},
            ],
            model="m",
        )
        tail = body["messages"][-1]
        assert tail["role"] == "user"
        assert [b["tool_use_id"] for b in tail["content"]] == ["a", "b"], (
            "拆成两条 user = 第二条没有前置 tool_use，协议判非法"
        )

    def test_non_string_tool_result_is_serialized_not_reprd(self):
        body = build_anthropic_body(
            [
                {"role": "user", "content": "q"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c", "type": "function", "function": {"name": "s", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "c", "content": {"ok": True}},
            ],
            model="m",
        )
        payload = body["messages"][-1]["content"][0]["content"]
        assert payload == '{"ok": true}', f"结构化结果要 JSON，不是 Python repr：{payload!r}"

    def test_unparsable_arguments_do_not_raise(self):
        """模型给出坏 JSON 参数时交诚实原文，而不是让整次请求装配抛异常。"""
        body = build_anthropic_body(
            [
                {"role": "user", "content": "q"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "d", "type": "function", "function": {"name": "s", "arguments": "{oops"}}
                    ],
                },
            ],
            model="m",
        )
        assert body["messages"][-1]["content"][0]["input"] == {"raw": "{oops"}

    def test_openai_multimodal_parts_become_anthropic_blocks(self):
        """ perception 图与文本并列：OpenAI 的 `image_url` 形态 → Anthropic 的 `image` 源块。

        改前这里 `str(content)` 会把整个 list 拍成一句 repr 文本——图就这样进了 prompt
        字符串，模型收到的是字面量 `[{'type': ...}]`。
        """
        body = build_anthropic_body(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "看这张图"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                        },
                    ],
                }
            ],
            model="m",
        )
        blocks = body["messages"][0]["content"]
        assert [b["type"] for b in blocks] == ["text", "image"]
        assert blocks[0]["text"] == "看这张图"
        assert blocks[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}

    def test_computer_descriptor_becomes_versioned_tool(self):
        """环只交**协议中立的能力参数**，Anthropic 的版本串由这一层拼。

        `computer_20241022` 是线协议细节，属于 provider 层；留在环里就是"谁该用哪种
        形状"的第二处定义。
        """
        body = build_anthropic_body(
            [{"role": "user", "content": "点一下"}],
            model="m",
            tools=[
                {"type": "computer", "name": "computer", "display_width_px": 1024,
                 "display_height_px": 768, "display_number": 1}
            ],
        )
        assert body["tools"][0]["type"] == "computer_20241022"
        assert body["tools"][0]["name"] == "computer"
        assert body["tools"][0]["display_width_px"] == 1024


class TestEndpointUrl:
    def test_official_base(self):
        assert anthropic_endpoint_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"

    def test_v1_suffixed_base(self):
        assert anthropic_endpoint_url("https://developer.amd.com.cn/radeon/api/v1") == (
            "https://developer.amd.com.cn/radeon/api/v1/messages"
        )


class TestClientDuckTyping:
    """multi_model_client 消费的鸭子接口：count_tokens/count_message_tokens"""

    def _client(self):
        cfg = LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        return AnthropicNativeClient(cfg)

    def test_count_tokens_rough(self):
        c = self._client()
        assert c.count_tokens("abcd" * 10) == 10
        assert c.count_message_tokens([{"role": "user", "content": "hi"}]) > 0

    def test_stream_sync_rejects_inside_loop(self):
        c = self._client()
        # B-11 防复活锁存对齐：Native 客户端不提供同步 chat_stream
        # （同步桥每 chunk 新建事件循环、零运行时调用方，已判死删除）；
        # 流式主路径只有 chat_stream_async
        assert not hasattr(c, "chat_stream"), (
            "同步 chat_stream 桥不得复活（B-11 判定删除，见 "
            "test_b11_no_sync_stream_bridge_revival.py）"
        )

    @pytest.mark.asyncio
    async def test_chat_normalizes_response(self, monkeypatch):
        c = self._client()
        async def fake_post(body):
            return {
                "content": [
                    {"type": "thinking", "thinking": "想"},
                    {"type": "text", "text": "答"},
                ],
                "stop_reason": "end_turn",
                "model": body["model"],
            }
        monkeypatch.setattr(c, "_post_json", fake_post)
        resp = await c.chat([{"role": "user", "content": "hi"}], thinking_effort="deep")
        assert resp.reasoning_content == "想"
        assert resp.content == "答"
        assert resp.finish_reason == "stop"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
