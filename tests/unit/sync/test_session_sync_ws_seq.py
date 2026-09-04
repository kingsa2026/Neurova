"""sync WS 端点 seq 握手契约测试（OpenOcta 启发 P0-1 配套）

- 连接建立先发 sync_hello{next_seq}（纪元探测），后发历史重放（带 seq）
  ——顺序不能反：纪元更迭时客户端必须先重置游标再收重放帧，否则重放
  被陈旧游标误吞
- sync_resume{last_seq} 定向补发 seq > last_seq 的历史事件，终止帧
  sync_resume_done（无可补发时也发，客户端以此对齐）
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import session_sync


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(session_sync.router, prefix="/api/v1/sync")
    return TestClient(app)


class TestSyncWsSeqHandshake:
    def test_hello_precedes_history_and_carries_next_seq(self, client):
        with client.websocket_connect("/api/v1/sync/ws/ws-seq-hello?channel_type=web&user_id=u1") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "sync_hello"
            assert isinstance(hello["next_seq"], int) and hello["next_seq"] >= 1
            # 随后是历史重放：register_or_create_session 写入的 SESSION_CREATED（seq=1）
            replayed = ws.receive_json()
            assert replayed.get("event_type") == "session_created"
            assert replayed.get("seq") == 1

    def test_sync_resume_replays_events_above_cursor(self, client):
        with client.websocket_connect("/api/v1/sync/ws/ws-seq-resume?channel_type=web&user_id=u1") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "sync_hello"
            # 初始重放：SESSION_CREATED(1) + register_channel 写入的 CHANNEL_CONNECTED(2)
            r1 = ws.receive_json()
            r2 = ws.receive_json()
            assert (r1["seq"], r2["seq"]) == (1, 2)

            # 游标 1 → 定向补发 seq>1（CHANNEL_CONNECTED）+ done 终止帧
            ws.send_json({"type": "sync_resume", "last_seq": 1})
            resumed = ws.receive_json()
            assert resumed.get("seq") == 2
            assert ws.receive_json() == {"type": "sync_resume_done"}

            # 游标超出当前发号器 → 无可补发，仅 done（不可作为纪元更迭判据，
            # 客户端纪元判定只看 sync_hello）
            ws.send_json({"type": "sync_resume", "last_seq": 100})
            assert ws.receive_json() == {"type": "sync_resume_done"}
