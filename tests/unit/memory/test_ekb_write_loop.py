"""EKB 经验知识库写入闭环回归测试（TDD）

断点：ExperienceKnowledgeBase 是注入侧 _build_experience_context 的数据源，
但生产代码只有读取没有写入（add_experience_record 零调用方）——
"相关经验"注入永远查不到对话沉淀的经验。
修复：post_chat_pipeline._step_record_experience 在记录到进化系统的同时
同步写一条经验记录进 EKB。
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


def _make_pipeline(tools_used=("web_search",), success=True):
    from neurova.post_chat_pipeline import PostChatPipeline

    agent = MagicMock()
    agent._collect_tool_messages.return_value = [
        {"tool_name": tools_used[0], "success": success}
    ]
    pipeline = PostChatPipeline(agent)

    evolution = MagicMock()
    evolution.on_experience_recorded = MagicMock()
    pipeline._dependencies["evolution"] = evolution
    return pipeline


@pytest.mark.asyncio
async def test_record_experience_writes_to_ekb():
    pipeline = _make_pipeline()
    with patch(
        "neurova.skills.experience_knowledge_base.ExperienceKnowledgeBase.add_experience_record"
    ) as mock_add:
        await pipeline._step_record_experience(
            user_input="帮我查天气", reply="今天晴", save_memory=True
        )
        mock_add.assert_called_once()
        kwargs = mock_add.call_args.kwargs
        exp = kwargs["exp"]
        assert exp.success is True
        assert "帮我查天气" in exp.context.get("user_input", "")


@pytest.mark.asyncio
async def test_record_experience_survives_ekb_failure():
    """EKB 写入失败不得影响经验记录主流程"""
    pipeline = _make_pipeline()
    with patch(
        "neurova.skills.experience_knowledge_base.ExperienceKnowledgeBase.add_experience_record",
        side_effect=RuntimeError("db locked"),
    ):
        await pipeline._step_record_experience(
            user_input="q", reply="r", save_memory=True
        )
    statuses = [r.status for r in pipeline._step_results]
    assert "failed" not in [str(s).lower() for s in statuses]
