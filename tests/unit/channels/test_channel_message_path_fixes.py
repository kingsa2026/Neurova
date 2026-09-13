# -*- coding: utf-8 -*-
"""渠道消息通路修复回归（飞书 sender 取 open_id / 轨迹路径消毒 / llm chat 去重 stream）。

这三处是 ChannelRouter 打通后飞书实测"收到消息但无回复"时暴露的真 bug：
1. 飞书外部用户 sender_id.user_id 为 null（只有 open_id）→ sender=None →
   router user_id 落到带冒号回退值。
2. save_trace 用 user_id/agent_id/session_id 当目录名，含 ":" → Windows WinError 123
   → agent.chat 崩 → 无回复。
3. LLMClient.chat() 显式 stream=False 又 **kwargs 带 stream → "multiple values for 'stream'"。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter


# ------------------------------------------------------------------
# 1. 飞书 sender 取 open_id 回退
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feishu_sender_falls_back_to_open_id():
    ad = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="a", app_secret="b",
                                     use_stream=True, extra={}))
    events = []

    async def cb(et, msg):
        events.append(msg)

    ad.set_event_callback(cb)
    event = SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text", content=json.dumps({"text": "你好"}),
                message_id="om_1", chat_id="oc_1", chat_type="p2p",
            ),
            # user_id=null（外部用户），只有 open_id
            sender=SimpleNamespace(sender_id=SimpleNamespace(user_id=None, open_id="ou_abc", union_id=None)),
        ),
    )
    loop = asyncio.get_running_loop()
    ad._main_loop = loop
    ad._handle_message_event(event)
    for _ in range(50):
        if events:
            break
        await asyncio.sleep(0.01)
    assert events, "消息未被处理"
    assert events[0].sender_id == "ou_abc", "user_id 为 null 时须回退 open_id"


# ------------------------------------------------------------------
# 2. save_trace 路径消毒（冒号/斜杠不崩）
# ------------------------------------------------------------------

def test_save_trace_sanitizes_windows_unsafe_chars(tmp_path):
    from pathlib import Path
    from neurova.core import trace_recorder as tr

    # 单例：重置后构造，存储目录指向 tmp
    tr.TrajectoryRecorder._instance = None
    tr.TrajectoryRecorder._initialized = False
    rec = tr.TrajectoryRecorder()
    rec._storage_dir = Path(tmp_path)
    rec._enabled = True
    # 渠道 user_id 带冒号、session 带冒号——旧实现 mkdir 直接 WinError
    trace_id = rec.start_trace(
        session_id="chan:feishu:oc_1", agent_id="default", user_id="channel:feishu",
    )
    rec.record_event(trace_id=trace_id, event_type="user_input", data={"user_input": "hi"})
    rec.end_trace(trace_id)  # 内部 save_trace → 不得抛 WinError 123
    files = list(Path(tmp_path).rglob("*.json"))
    assert files, "轨迹未落盘"
    assert all(":" not in p.parent.name for p in files), "目录名仍含冒号"
    tr.TrajectoryRecorder._instance = None
    tr.TrajectoryRecorder._initialized = False


# ------------------------------------------------------------------
# 3. LLMClient.chat 不再重复传 stream
# ------------------------------------------------------------------

def test_llm_chat_does_not_duplicate_stream(monkeypatch):
    from neurova import llm_client as lc

    calls = {}

    class _Stop(Exception):
        pass

    client = lc.LLMClient.__new__(lc.LLMClient)
    client._initialized = True
    client.client = object()  # 非空即可（真正 create 前就在 _build_request_params 边界停）
    client.logger = SimpleNamespace(warning=lambda *a, **k: None)
    client.config = SimpleNamespace(model="m", max_input_tokens=0, max_tokens=100)

    def fake_build(messages, stream=False, **kw):
        # 记录显式 stream 与 kwargs 里是否残留 stream（残留即旧 bug 的冲突源）
        calls["stream"] = stream
        calls["kwargs_has_stream"] = "stream" in kw
        raise _Stop()  # 到边界即停，不触真实网络

    monkeypatch.setattr(client, "_build_request_params", fake_build)
    monkeypatch.setattr(client, "_check_input_budget", lambda *a, **k: None)
    with pytest.raises(Exception):
        client.chat([{"role": "user", "content": "hi"}], stream=True)
    # 关键：kwargs 里的 stream 必须被剥离，否则 _build_request_params 收到两个 stream → TypeError
    assert calls.get("kwargs_has_stream") is False, "chat() 未剥离 kwargs 里的 stream → 会 multiple values"
    assert calls.get("stream") is False
