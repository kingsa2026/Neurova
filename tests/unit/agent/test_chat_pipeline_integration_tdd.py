"""ChatContext 契约测试。

历史：本文件原为 PipelineExecutor 集成测试；该未接线的门面已随死代码清理删除，
此处仅保留与被删实现无关的 ChatContext.enable_tts 契约断言。
"""

import pytest

from neurova.agent.chat_pipeline import ChatContext


class TestChatContextEnableTts:
    def test_context_has_enable_tts_field(self):
        ctx = ChatContext(user_input="test", enable_tts=True)
        assert ctx.enable_tts is True

    def test_context_default_enable_tts(self):
        ctx = ChatContext(user_input="test")
        assert ctx.enable_tts is False
