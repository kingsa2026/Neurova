# -*- coding: utf-8 -*-
"""语音口令确认（B4-9 HITL）：模型口头问询、用户口头"好"才算确认。

判据：
- 词法闸：整句肯定才算（长句里碰巧含"好"不算）；
- confirmByVoiceTranscript 走 approve_request 同一收敛路径（终态/审计一致）；
- 渠道回灌：恰一张待审单 + 整句肯定 → 确认；多张不猜；非肯定/非语音不动作；
- 反自答是结构性的：回灌只发生在入站用户语音消息路径（本文件即模拟该路径）。
"""
import time

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_router import _tryVoiceConfirmPendingApprovals
from neurova.security.approval_manager import (
    ApprovalManager,
    affirmativeVoiceTranscript,
)


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    m = ApprovalManager(workspace_path=str(tmp_path / "ws"))
    monkeypatch.setattr("neurova.security.approval_manager._approval_manager", m)
    yield m


def _msg(content, voice=True):
    metadata = {"voice_transcribed": True} if voice else {}
    return ChannelMessage(
        channel_type="telegram",
        message_id=f"m{time.time_ns()}",
        sender_id="u1",
        sender_name="用户",
        content=content,
        chat_id="c1",
        chat_type="p2p",
        metadata=metadata,
    )


class TestAffirmativeTranscript:
    def test_bare_affirmations(self):
        for t in ("好的", "好", "可以", "确认", "同意", "没错", "就这样", "行",
                  "yes", "ok", "Okay!", "批准"):
            assert affirmativeVoiceTranscript(t), t

    def test_long_sentence_with_affirm_char_is_not(self):
        assert not affirmativeVoiceTranscript("这个方案好不好")
        assert not affirmativeVoiceTranscript("好的，不过我还想补充一点")
        assert not affirmativeVoiceTranscript("不行")

    def test_empty_or_noise(self):
        assert not affirmativeVoiceTranscript("")
        assert not affirmativeVoiceTranscript("嗯……让我想想")


class TestConfirmByVoiceTranscript:
    def test_confirm_approves_pending_request(self, manager):
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="rm -rf /tmp/x",
            description="删除临时目录", danger_reason="危险命令",
        )
        assert manager.confirmByVoiceTranscript(req.request_id, "好的", user_id="u1") is True
        settled = manager.get_request(req.request_id)
        assert settled.status.value == "approved"
        assert settled.approval_note.startswith("voice:"), "确认留转写原文可追溯"

    def test_confirm_is_idempotent_on_settled(self, manager):
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="ls -la", description="列目录"
        )
        assert manager.confirmByVoiceTranscript(req.request_id, "好的", user_id="u1") is True
        assert manager.confirmByVoiceTranscript(req.request_id, "好的", user_id="u1") is False


class TestChannelRouterHook:
    def test_single_pending_and_affirmative_confirms(self, manager):
        req = manager.create_approval_request(
            agent_id="a1", user_id="u1", command="rm -rf /tmp/y",
            description="删除", danger_reason="危险命令",
        )
        _tryVoiceConfirmPendingApprovals("a1", _msg("好的"))
        assert manager.get_request(req.request_id).status.value == "approved"

    def test_multiple_pending_does_not_guess(self, manager):
        manager.create_approval_request(agent_id="a2", user_id="u1",
                                        command="rm -rf /a", description="一")
        manager.create_approval_request(agent_id="a2", user_id="u1",
                                        command="rm -rf /b", description="二")
        _tryVoiceConfirmPendingApprovals("a2", _msg("好的"))
        for r in manager.get_pending_requests(agent_id="a2"):
            assert r.status.value == "pending", "多张待审不猜，保持待审"

    def test_non_affirmative_does_nothing(self, manager):
        req = manager.create_approval_request(agent_id="a3", user_id="u1",
                                              command="rm -rf /c", description="三")
        _tryVoiceConfirmPendingApprovals("a3", _msg("帮我看看这个"))
        assert manager.get_request(req.request_id).status.value == "pending"

    def test_non_voice_message_never_confirms(self, manager):
        """反自答的另一半：非语音（打字/机器人自产）消息不触发确认。"""
        req = manager.create_approval_request(agent_id="a4", user_id="u1",
                                              command="rm -rf /d", description="四")
        _tryVoiceConfirmPendingApprovals("a4", _msg("好的", voice=False))
        assert manager.get_request(req.request_id).status.value == "pending"
