# -*- coding: utf-8 -*-
"""远程驾驶可靠性通道测试（实施计划项 1：连接 epoch + 事件账本重放 + 指令记账）。

验收判据（计划项 1）：手机断网 30s 内的遥控指令不丢、不重复执行；重连后状态一致。

三层锁定：
1. MobileWsLedger 存储层——连接 epoch 递增、事件追加单调 seq、按游标重放、
   指令 begin 幂等（按设备隔离）+ 终态回放；
2. WS 集成——同 command_id 的 chat:send 只执行一次（第二次回放原终态）；
   sync_resume 按游标补发缺失帧（带 replay 标记）；
3. 兼容——不带 command_id 的旧客户端行为不变（每条新指令照常执行）。
"""
import inspect
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep

PAIRING_CODE = "MOBILE-CODE-1"
OWNER = "u-drive"
AGENT_ID = "drive-agent"


def _checkAgainstRealSignature(agent, methodName: str, kwargs: Dict[str, Any], sink: List[dict]):
    """按真 `Agent.<method>` 的签名 bind 一遍：参数名不对、必填没给，都在这一步抛
    （替身不自己声明签名——手抄清单会随生产签名漂移，见 test_mobilePairingChatSendContract）。"""
    from neurova.agent_core import Agent

    signature = inspect.signature(getattr(Agent, methodName))
    signature.bind(None, **kwargs)
    sink.append({**kwargs})


class _StreamAgent:
    """真 `Agent.chat` 契约的替身：事件经 metadata.event_emitter 流出、
    返回整段回复 dict；calls 计数用于断言"只执行一次"。
    （`_handle_chat_send` await 的是 `agent.chat(...)` 一次，不是迭代
    chat_stream——流式增量走 event_emitter 回调。）"""

    def __init__(self) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, **kwargs):
        _checkAgainstRealSignature(self, "chat", kwargs, self.calls)
        emit = (kwargs.get("metadata") or {}).get("event_emitter")
        for piece in ("第一段", "第二段"):
            if emit is not None:
                emit("content", piece)
        return {"text": "第一段第二段", "success": True}


@pytest.fixture(autouse=True)
def _freshRunStateSingletons(tmp_path, monkeypatch):
    """台账/让位闸/移动 WS 账本单例逐测重置并清空行：占位行、计时状态与
    指令账目不泄漏进其他测试（与 test_mobilePairingChatSendContract.py 同一
    隔离口径，缺它回合会被让位闸挂起、客户端永远等不到终态帧）。"""
    import asyncio

    from neurova.api import mobile_ws_ledger as wsledger
    from neurova.collaboration import glance_yield_rules as gyr
    from neurova.core import agent_run_store as ars

    monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger.db"))
    wsledger.resetMobileWsLedger()
    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()
    yield
    wsledger.resetMobileWsLedger()
    asyncio.run(gyr.reset_glance_yield_checker())
    ars.reset_agent_run_store()
    store = ars.get_agent_run_store()
    with store._lock:
        store._conn.execute("DELETE FROM agent_runs")
        store._conn.commit()


@pytest.fixture()
def wsClient(monkeypatch):
    agent = _StreamAgent()
    import neurova.api.endpoints as endpointsModule

    # `get_agent_instance` 在 `_handle_chat_send` 里就近 import（模块级没有这个名字），
    # 要打在它的出处 `neurova.api.endpoints` 上。
    monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": agent)

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-drive"},
    )

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.agent = agent  # type: ignore[attr-defined]
    return client


def _driveChat(client, content: str, sessionId: str, commandId: str = "") -> List[Dict[str, Any]]:
    """一条连接内发一条 chat:send 并读到终态；返回收到的帧序列。"""
    frames: List[Dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
        payload: Dict[str, Any] = {"type": "chat:send", "content": content, "session_id": sessionId}
        if commandId:
            payload["command_id"] = commandId
        ws.send_json(payload)
        while True:
            frame = json.loads(ws.receive_text())
            frames.append(frame)
            if frame.get("type") in ("chat:done", "error", "chat:cancelled"):
                break
    return frames


class TestMobileWsLedgerStorage:
    """存储层：epoch 递增、事件单调 seq、按游标重放、指令幂等（按设备隔离）。"""

    @pytest.fixture()
    def ledger(self, tmp_path):
        from neurova.api import mobile_ws_ledger

        store = mobile_ws_ledger.MobileWsLedger(db_path=tmp_path / "ws_ledger.db")
        yield store
        store.close()

    def test_epoch_increments_per_pairing(self, ledger):
        assert ledger.nextEpoch("pair-1") == 1
        assert ledger.nextEpoch("pair-1") == 2
        assert ledger.nextEpoch("pair-2") == 1  # 不同设备各自计数

    def test_append_assigns_monotonic_seq(self, ledger):
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "content": "a"})
        s2 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "content": "b"})
        assert s2 > s1 > 0

    def test_replay_since_returns_only_later_frames(self, ledger):
        seqs = [ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "content": c})
                for c in ("a", "b", "c", "d")]
        rows = ledger.replaySince("pair-1", seqs[1])
        assert [r["seq"] for r in rows] == seqs[2:]
        assert rows[0]["frame"]["content"] == "c"

    def test_replay_is_pairing_scoped(self, ledger):
        s_other = ledger.appendEvent("pair-2", 1, {"type": "chat:chunk", "content": "x"})
        s_own = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "content": "y"})
        rows = ledger.replaySince("pair-1", 0)
        assert [r["seq"] for r in rows] == [s_own]
        assert s_other not in [r["seq"] for r in rows]

    def test_command_dedup_and_terminal_replay(self, ledger):
        entry, prior = ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        assert prior is None and entry.status == "running"
        ledger.settleCommand("cmd-1", "pair-1", {"type": "chat:done", "session_id": "s-1"})

        entry2, prior2 = ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        assert entry2.command_id == entry.command_id
        assert prior2 is not None
        assert prior2["type"] == "chat:done"
        assert prior2["replayed"] is True

    def test_command_running_is_reported(self, ledger):
        ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        entry, prior = ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        assert entry.status == "running"
        assert prior is not None and prior["code"] == "command_already_running"

    def test_command_scoped_per_device(self, ledger):
        """command_id 由各设备自行生成（cmd-1 递增是常态）：不同设备的同名指令
        互不干扰——全局按 command_id 去重会把第二台手机的新指令误判成重放。"""
        _, prior1 = ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "a"})
        _, prior2 = ledger.beginCommand("cmd-1", "pair-2", "chat:send", {"content": "b"})
        assert prior1 is None and prior2 is None
        # 一台收敛不影响另一台的运行态
        ledger.settleCommand("cmd-1", "pair-1", {"type": "chat:done"})
        _, priorAgain = ledger.beginCommand("cmd-1", "pair-2", "chat:send", {"content": "b"})
        assert priorAgain is not None and priorAgain["code"] == "command_already_running"

    def test_failed_command_settles_with_error_frame(self, ledger):
        """失败回合也要收敛：否则失败指令永远停在 running，同 id 重试只会
        得到 already_running，永远拿不到真实失败原因。"""
        ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        ledger.settleCommand("cmd-1", "pair-1", {"type": "error", "code": "chat_failed",
                                                 "message": "boom"})
        _, prior = ledger.beginCommand("cmd-1", "pair-1", "chat:send", {"content": "hi"})
        assert prior is not None
        assert prior["type"] == "error" and prior["code"] == "chat_failed"
        assert prior["replayed"] is True

    def test_legacy_single_pk_table_migrates_to_composite(self, tmp_path):
        """存量库迁移：v1 旧形（command_id 单列主键）打开时须重建为
        (pairing_id, command_id) 复合主键并保留全部行——IF NOT EXISTS 不会改
        已有表，裸演进会让重发指令在真后端上撞旧主键后查无此行。"""
        import sqlite3

        from neurova.api import mobile_ws_ledger

        dbPath = tmp_path / "legacy.db"
        conn = sqlite3.connect(dbPath)
        conn.execute("""
            CREATE TABLE mobile_ws_commands (
                command_id TEXT PRIMARY KEY,
                pairing_id TEXT NOT NULL,
                cmd_type TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                terminal_json TEXT,
                created_at REAL NOT NULL DEFAULT 0,
                settled_at REAL
            )
        """)
        conn.execute(
            "INSERT INTO mobile_ws_commands (command_id, pairing_id, status, created_at)"
            " VALUES ('cmd-1', 'pair-old', 'settled', 1.0)"
        )
        conn.commit()
        conn.close()

        store = mobile_ws_ledger.MobileWsLedger(db_path=dbPath)
        try:
            cols = {r[1]: r[5] for r in store._conn.execute(
                "PRAGMA table_info(mobile_ws_commands)").fetchall()}
            pkOrder = [name for name, pk in sorted(cols.items(), key=lambda kv: kv[1]) if pk]
            assert pkOrder == ["pairing_id", "command_id"], f"主键未升级：{pkOrder}"
            # 旧行保留，且同 command_id 在新设备上不再是重放
            _, priorOld = store.beginCommand("cmd-1", "pair-old", "chat:send", {})
            assert priorOld is not None, "旧设备已收敛指令仍应回放"
            _, priorNew = store.beginCommand("cmd-1", "pair-new", "chat:send", {})
            assert priorNew is None, "新设备的同名指令不应被旧设备账目拦下"
        finally:
            store.close()


class TestRemoteDrivingWebSocket:
    """WS 集成：同指令只执行一次；sync_resume 补发缺失帧；不破坏既有契约。"""

    def test_same_command_id_executes_once(self, wsClient):
        first = _driveChat(wsClient, "你好", "s-1", commandId="cmd-1")
        second = _driveChat(wsClient, "你好", "s-1", commandId="cmd-1")

        assert len(wsClient.agent.calls) == 1, "同 command_id 的第二次发送不得再执行"
        terminal = second[-1]
        assert terminal.get("replayed") is True
        assert terminal.get("type") == "chat:done"
        assert first[-1].get("replayed") is None

    def test_sync_resume_replays_missed_frames(self, wsClient):
        frames = _driveChat(wsClient, "你好", "s-1", commandId="cmd-1")
        seqs = [f["seq"] for f in frames]
        assert all(isinstance(s, int) for s in seqs), "账本化后每帧都应带单调 seq"

        # 第二条连接从首帧之前补拉：应收到全部缺失帧（带 replay 标记）
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "sync_resume", "last_seq": seqs[0] - 1})
            replayed: List[Dict[str, Any]] = []
            while len(replayed) < len(frames):
                frame = json.loads(ws.receive_text())
                if frame.get("replay") is True:
                    replayed.append(frame)
            assert [f["seq"] for f in replayed] == seqs, "重放应按原 seq 逐帧补齐"

    def test_no_hello_injected_without_resume(self, wsClient):
        """兼容判据：不发 sync_resume 就不会有额外首帧（既有契约 events[0]=chat:chunk 不破）。"""
        frames = _driveChat(wsClient, "你好", "s-1")
        assert frames[0]["type"] == "chat:chunk", frames[0]

    def test_epoch_grows_across_connections(self, wsClient):
        frames1 = _driveChat(wsClient, "你好", "s-1", commandId="cmd-1")
        frames2 = _driveChat(wsClient, "你好", "s-2", commandId="cmd-2")
        assert frames2[0]["epoch"] > frames1[0]["epoch"]
