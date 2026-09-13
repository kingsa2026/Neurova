# -*- coding: utf-8 -*-
"""可读标题 + QQ/企微群回复@ 测试（阶段3/4 收尾）。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from neurova.channels.base import ChannelConfig, ChannelMessage


# ---------- 可读标题：add_message title 入参 ----------

def test_add_message_creation_uses_title(tmp_path, monkeypatch):
    from neurova import session_manager as sm_mod
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    sm_mod.SessionManager._instance = None
    sm = sm_mod.SessionManager()
    sm.add_message("default", "sess_t1", "用户问", "助手答", metadata={}, user_id="admin",
                   title="feishu·张三")
    files = list((tmp_path / "sessions").rglob("session_sess_t1_*.json"))
    assert files, "会话文件未生成"
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["title"] == "feishu·张三"
    # 已存在的会话再 add_message 不覆盖标题（仅建记录时生效）
    sm.add_message("default", "sess_t1", "再问", "再答", metadata={}, user_id="admin",
                   title="被忽略的标题")
    data2 = json.loads(files[0].read_text(encoding="utf-8"))
    assert data2["title"] == "feishu·张三"
    sm_mod.SessionManager._instance = None


def test_add_message_accepts_title_kwarg():
    import inspect
    from neurova.session_manager import SessionManager
    sig = inspect.signature(SessionManager.add_message)
    assert "title" in sig.parameters


# ---------- channel_router 注入 session_title ----------

def _msg(content="嗨", channel_type="feishu", chat_id="oc_1", sender="ou_9", name="张三", chat_type="p2p"):
    return ChannelMessage(
        channel_type=channel_type, message_id="m1", sender_id=sender, sender_name=name,
        content=content, chat_id=chat_id, chat_type=chat_type, metadata={"agent_id": "default"},
    )


@pytest.mark.asyncio
async def test_channel_router_sets_readable_session_title():
    from neurova.channels import channel_router
    from neurova.channels.manager import ChannelManager
    ChannelManager._instance = None
    mgr = ChannelManager()
    seen = {}
    class FakeAgent:
        owner_user_id = "admin"
        async def chat(self, user_input, session_id=None, metadata=None, **kw):
            seen["meta"] = metadata
            return {"text": "ok"}
    handler = channel_router.make_handler(mgr, agent_lookup=lambda aid: FakeAgent())
    await handler(_msg("你好", name="张三"))
    assert seen["meta"]["session_title"] == "feishu·张三"
    await handler(_msg("群消息", chat_type="group", name="研发群"))
    assert seen["meta"]["session_title"] == "feishu群·研发群"
    ChannelManager._instance = None


# ---------- QQ 群回复 @ ----------

@pytest.mark.asyncio
async def test_qq_group_reply_includes_at(monkeypatch):
    from neurova.channels import qq_ws
    captured = {}
    class _R:
        status_code = 200
        def json(self): return {"id": "sent-1"}
    monkeypatch.setattr(qq_ws.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: (captured.update(body=json) or _R()))
    a = qq_ws.QQWebSocketAdapter(ChannelConfig(channel_type="qq", app_id="a", app_secret="s", extra={}))
    a.access_token = "t"; a.token_expire_time = float("inf")
    a._last_msg_id["gr_1"] = "MSG1"
    await a.send_message("gr_1", "群回复", "text", chat_type="group", at_user_id="mb_9",
                         qq_message_type="group")
    assert captured["body"]["at"] == {"name": "", "qq": "mb_9", "type": 3}


@pytest.mark.asyncio
async def test_qq_p2p_reply_no_at(monkeypatch):
    from neurova.channels import qq_ws
    captured = {}
    class _R:
        status_code = 200
        def json(self): return {"id": "s"}
    monkeypatch.setattr(qq_ws.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: (captured.update(body=json) or _R()))
    a = qq_ws.QQWebSocketAdapter(ChannelConfig(channel_type="qq", app_id="a", app_secret="s", extra={}))
    a.access_token = "t"; a.token_expire_time = float("inf")
    a._last_msg_id["u_1"] = "MSG1"
    await a.send_message("u_1", "私聊", "text", chat_type="p2p", at_user_id="u_1")
    assert "at" not in captured["body"]
