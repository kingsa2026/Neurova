"""
后处理管线单元测试

测试PostChatPipeline的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from neurova.post_chat_pipeline import PostChatPipeline


class TestPostChatPipeline:
    """PostChatPipeline测试"""
    
    def test_init(self):
        """测试初始化"""
        agent_ref = Mock()
        pipeline = PostChatPipeline(agent_ref)
        assert pipeline is not None
