"""
工具使用与创建 Bug 的 TDD RED 测试

发现于 bug-hunt Phase 1（zoom-out 全局架构审查）。
每个测试类对应一个已确认的 bug，复现其失败行为。

Bug 清单:
  T-1: chat_pipeline._check_nl_synthesis 调用 synthesize(author_id=...) 签名不匹配 → TypeError
  T-2: chat_pipeline._check_nl_synthesis 访问 synth_result.stage/tool/confidence 字段不存在 → AttributeError
  T-3: nl_synthesizer._generate_tool_name 正则匹配中文，生成含中文工具名违反 OpenAI 规范
  T-4: tool_executor._execute_from_text 不写入 _tool_messages_list，前端工具结果丢失

注意: 工作区 neurova/core/ 被删除时无法运行；恢复后应全部 RED→GREEN。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from neurova.evolution.nl_synthesizer import (
    NLToolSynthesizer,
    ToolSynthesisResult,
    SynthesizedTool,
    SynthesisStage,
)


# ══════════════════════════════════════════════════════════════
# T-1: synthesize 签名不匹配 — chat_pipeline 传了不存在的 author_id 参数
# ══════════════════════════════════════════════════════════════


class TestT1SynthesizeSignatureMismatch:
    """T-1: chat_pipeline.py:534 调用 synthesize(description=..., author_id=...)，
    但 NLToolSynthesizer.synthesize 签名是 (description, context=None)，不接受 author_id。

    根因: 调用方假设的接口与实际接口不一致，TypeError 被外层 except 吞掉，
    导致 NL 工具合成永远静默失败。
    """

    def test_synthesize_does_not_accept_author_id(self):
        """RED: synthesize() 不应接受 author_id 参数（当前会抛 TypeError）"""
        synth = NLToolSynthesizer()

        # 模拟 chat_pipeline.py:534-537 的调用方式
        with pytest.raises(TypeError):
            synth.synthesize(
                description="帮我搜索文件",
                author_id="test_agent",  # ← 不存在的参数
            )

    def test_synthesize_accepts_context_dict(self):
        """GREEN 目标: synthesize 应通过 context 传递 agent 标识"""
        synth = NLToolSynthesizer()
        result = synth.synthesize(
            description="帮我搜索文件",
            context={"author_id": "test_agent"},
        )
        # 应返回 ToolSynthesisResult，而非抛 TypeError
        assert isinstance(result, ToolSynthesisResult)


# ══════════════════════════════════════════════════════════════
# T-2: synth_result 字段访问错误 — stage/tool/confidence 不在 ToolSynthesisResult 上
# ══════════════════════════════════════════════════════════════


class TestT2SynthesisResultFieldError:
    """T-2: chat_pipeline.py:538-539 访问 synth_result.stage / synth_result.tool / synth_result.confidence，
    但 ToolSynthesisResult 的字段是 success/synthesized_tool/error_message/...，
    stage/name/confidence 在 SynthesizedTool 上（即 synth_result.synthesized_tool.stage）。

    根因: 调用方混淆了 ToolSynthesisResult 和 SynthesizedTool 的字段。
    """

    def test_tool_synthesis_result_has_no_stage_field(self):
        """RED: ToolSynthesisResult 无 stage 字段"""
        result = ToolSynthesisResult()
        assert not hasattr(result, "stage"), "ToolSynthesisResult 不应有 stage 字段"

    def test_tool_synthesis_result_has_no_tool_field(self):
        """RED: ToolSynthesisResult 无 tool 字段（应为 synthesized_tool）"""
        result = ToolSynthesisResult()
        assert not hasattr(result, "tool"), "ToolSynthesisResult 不应有 tool 字段"

    def test_tool_synthesis_result_has_no_confidence_field(self):
        """RED: ToolSynthesisResult 无 confidence 字段（在 synthesized_tool 上）"""
        result = ToolSynthesisResult()
        assert not hasattr(result, "confidence"), "ToolSynthesisResult 不应有 confidence 字段"

    def test_correct_field_access_path(self):
        """GREEN 目标: 正确的字段访问路径是 synth_result.synthesized_tool.stage.name.confidence"""
        synth = NLToolSynthesizer()
        result = synth.synthesize(description="帮我搜索文件")

        # 正确访问路径（chat_pipeline.py:538-39 应改成这样）
        assert isinstance(result, ToolSynthesisResult)
        if result.success and result.synthesized_tool:
            tool = result.synthesized_tool
            # stage/name/confidence 都在 SynthesizedTool 上
            assert hasattr(tool, "stage")
            assert hasattr(tool, "name")
            assert hasattr(tool, "confidence")
            assert tool.stage.value == "completed"


# ══════════════════════════════════════════════════════════════
# T-3: _generate_tool_name 生成含中文工具名，违反 OpenAI function calling 规范
# ══════════════════════════════════════════════════════════════


class TestT3ChineseToolNameViolation:
    """T-3: nl_synthesizer.py:500 _generate_tool_name 的正则 [\\u4e00-\\u9fff] 匹配中文字符，
    导致工具名可能含中文（如 "帮我_搜索_文件_tool"）。

    OpenAI function calling 工具名规范: ^[a-zA-Z0-9_-]{1,64}$，不允许中文。
    这会导致 LLM 调用时 schema 被拒绝。
    """

    @pytest.mark.parametrize(
        "description,category",
        [
            ("帮我搜索文件", "search"),
            ("读取配置文件", "file"),
            ("下载网络资源", "web"),
        ],
    )
    def test_tool_name_contains_no_chinese(self, description, category):
        """RED: 当前 _generate_tool_name 对中文描述生成含中文的工具名"""
        synth = NLToolSynthesizer()
        name = synth._generate_tool_name(description, category)

        # OpenAI 规范: ^[a-zA-Z0-9_-]{1,64}$
        import re

        assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", name), (
            f"工具名 '{name}' 含非法字符（中文/特殊符号），违反 OpenAI function calling 规范"
        )

    def test_tool_name_uses_pinyin_or_category_fallback(self):
        """GREEN 目标: 中文描述应回退到 category 或转写为 ASCII"""
        synth = NLToolSynthesizer()
        name = synth._generate_tool_name("帮我搜索文件", "search")
        # 应回退到 category 或纯 ASCII
        import re

        assert re.match(r"^[a-zA-Z0-9_-]{1,64}$", name), f"工具名 '{name}' 应为纯 ASCII"


# ══════════════════════════════════════════════════════════════
# T-4: _execute_from_text 不写入 _tool_messages_list，前端工具结果丢失
# ══════════════════════════════════════════════════════════════


class TestT4ExecuteFromTextMissingMessages:
    """T-4: tool_executor.py:127-155 _execute_from_text 只把结果附加到 reply 字符串，
    不写入 agent._tool_messages_list。

    而 list 模式（line 203-209）会写入 _tool_messages_list。
    chat_pipeline.py:735 调用的是字符串模式（ctx.reply 是 str），
    所以前端 AGENT_TOOL_RESULT 事件的 tool_messages 永远为空。

    根因: 两种执行模式对工具结果的持久化行为不一致。
    """

    @pytest.mark.asyncio
    async def test_execute_from_text_writes_tool_messages_list(self):
        """RED: _execute_from_text 应写入 _tool_messages_list（当前不写）"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        # 让 _execute_single_tool 返回一个简单结果
        executor = ToolExecutor(mock_agent)
        executor._execute_single_tool = AsyncMock(return_value={"status": "ok"})

        reply_with_tool_call = '[TOOL_CALL:test_tool({"query": "hello"})]'
        await executor._execute_from_text(reply_with_tool_call, "hello")

        # 工具执行后，_tool_messages_list 应有记录（当前为空 → RED）
        assert len(mock_agent._tool_messages_list) > 0, (
            "_execute_from_text 应将工具结果写入 _tool_messages_list，"
            "否则前端 AGENT_TOOL_RESULT 事件收不到工具结果"
        )

    @pytest.mark.asyncio
    async def test_execute_from_text_tool_message_format(self):
        """GREEN 目标: _tool_messages_list 记录应符合 OpenAI tool message 格式"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        executor = ToolExecutor(mock_agent)
        executor._execute_single_tool = AsyncMock(return_value={"result": "data"})

        await executor._execute_from_text('[TOOL_CALL:search({"q": "test"})]', "test")

        if mock_agent._tool_messages_list:
            msg = mock_agent._tool_messages_list[0]
            assert msg["role"] == "tool"
            assert "content" in msg
            assert "tool_call_id" in msg or "name" in msg  # 至少有标识


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
