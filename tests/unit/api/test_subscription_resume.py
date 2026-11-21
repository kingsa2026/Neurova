# -*- coding: utf-8 -*-
"""D3 多端订阅自适应：游标续传决策 / 重连退避 / 帧去重（subscription_resume）行为钉子。

钉四条契约（PC / 鸿蒙 / 安卓三端统一语义的单源）：
1. resolveResumeMode：游标有效且落在可回放窗口与预算内 → replay；
   游标过旧（早于保留窗口下界，区间已有帧被修剪）/ 领先服务端头（非法）/
   预算已耗尽 / 缺失或负数 → snapshot，且 ResumeDecision 带诚实标注；
2. reconnectBackoff：2^n 指数退避封顶 cap；jitter 可注入（确定性），缺省 ±20% 随机；
3. dedupBySequence：按 seq 去重保序（重放 + 实时衔接处不重复）；
4. MobileWsLedger.resolveResume：移动 WS 账本接同一单源（留存窗口下界 →
   min_available_seq），端点 sync_resume 按决策走 replay / snapshot 两路。
"""
import json
from types import SimpleNamespace

import pytest

from neurova.api.subscription_resume import (
    ResumeDecision,
    dedupBySequence,
    reconnectBackoff,
    resolveResume,
    resolveResumeMode,
)
from neurova.api.ws_stream_budget import ReplayByteBudget


class TestResolveResumeMode:
    """游标续传决策单源。"""

    def test_游标在窗口内判replay(self):
        assert resolveResumeMode(5, 10) == "replay"
        assert resolveResumeMode(5, 10, min_available_seq=3) == "replay"
        # 无缝衔接边界：cursor+1 恰为保留窗口下界，回放不缺帧
        assert resolveResumeMode(2, 10, min_available_seq=3) == "replay"
        # 已追平服务端头：空回放（不是错误）
        assert resolveResumeMode(10, 10) == "replay"

    def test_游标过旧判snapshot并诚实标注(self):
        decision = resolveResume(1, 10, min_available_seq=5)
        assert decision.mode == "snapshot"
        assert decision.reason == "cursor_pruned"
        assert decision.note, "降级决策必须带诚实标注"

    def test_游标领先头判snapshot并诚实标注(self):
        decision = resolveResume(11, 10)
        assert decision.mode == "snapshot"
        assert decision.reason == "cursor_ahead_of_head"
        assert "11" in decision.note and "10" in decision.note

    def test_缺游标与非法游标判snapshot(self):
        assert resolveResumeMode(None, 10) == "snapshot"
        decision = resolveResume(-1, 10)
        assert decision.mode == "snapshot"
        assert decision.reason == "cursor_invalid"

    def test_空库上领先游标判snapshot(self):
        assert resolveResumeMode(1, 0) == "snapshot"

    def test_预算耗尽判snapshot_预算充足判replay(self):
        budget = ReplayByteBudget(10)
        budget.feed(10)
        assert resolveResumeMode(5, 10, budget=budget) == "snapshot"
        fresh = ReplayByteBudget(10)
        assert resolveResumeMode(5, 10, budget=fresh) == "replay"

    def test_决策对象字段完整(self):
        decision = resolveResume(5, 10)
        assert isinstance(decision, ResumeDecision)
        assert decision.mode == "replay"
        assert decision.reason == "cursor_in_window"


class TestReconnectBackoff:
    """三端统一重连退避语义。"""

    def test_指数退避封顶(self):
        assert reconnectBackoff(0, jitter_fn=lambda d: d) == 0.5
        assert reconnectBackoff(1, jitter_fn=lambda d: d) == 1.0
        assert reconnectBackoff(2, jitter_fn=lambda d: d) == 2.0
        assert reconnectBackoff(3, jitter_fn=lambda d: d) == 4.0
        assert reconnectBackoff(10, jitter_fn=lambda d: d) == 30.0, "超过封顶后恒为 cap"
        assert reconnectBackoff(100, jitter_fn=lambda d: d) == 30.0

    def test_自定义基数与封顶(self):
        assert reconnectBackoff(0, base_s=0.1, cap_s=1.0, jitter_fn=lambda d: d) == 0.1
        assert reconnectBackoff(5, base_s=0.1, cap_s=1.0, jitter_fn=lambda d: d) == 1.0

    def test_负数尝试按0处理(self):
        assert reconnectBackoff(-3, jitter_fn=lambda d: d) == 0.5

    def test_缺省jitter在正负20个百分点内(self):
        for attempt in range(6):
            base = min(0.5 * (2 ** attempt), 30.0)
            for _ in range(20):
                delay = reconnectBackoff(attempt)
                assert base * 0.8 <= delay <= base * 1.2

    def test_jitter注入决定论(self):
        # jitter_fn 收到封顶后的基础时延、返回最终时延：注入倍率序列即得确定结果
        factors = iter([1.0, 0.5, 1.2])
        assert reconnectBackoff(2, jitter_fn=lambda d: d * next(factors)) == 2.0
        assert reconnectBackoff(2, jitter_fn=lambda d: d * next(factors)) == 1.0
        assert reconnectBackoff(2, jitter_fn=lambda d: d * next(factors)) == 2.4


class TestDedupBySequence:
    """重放 + 实时衔接处的帧去重。"""

    def test_按seq去重保序(self):
        frames = [{"seq": 1}, {"seq": 2}, {"seq": 1}, {"seq": 3}, {"seq": 2}, {"seq": 4}]
        assert dedupBySequence(frames) == [{"seq": 1}, {"seq": 2}, {"seq": 3}, {"seq": 4}]

    def test_无seq帧不去重原样保留(self):
        frames = [{"seq": 1}, {"type": "pong"}, {"seq": 1}, {"type": "pong"}]
        assert dedupBySequence(frames) == [{"seq": 1}, {"type": "pong"}, {"type": "pong"}]

    def test_空输入返回空列表(self):
        assert dedupBySequence([]) == []
        assert dedupBySequence(None) == []


class TestMobileLedgerResolveResume:
    """移动 WS 账本接同一决策单源。"""

    @pytest.fixture()
    def ledger(self, tmp_path):
        from neurova.api import mobile_ws_ledger

        store = mobile_ws_ledger.MobileWsLedger(db_path=tmp_path / "ws_ledger.db")
        yield store
        store.close()

    def test_游标在窗口内判replay(self, ledger):
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk"})
        ledger.appendEvent("pair-1", 1, {"type": "chat:done"})
        assert ledger.resolveResume("pair-1", s1).mode == "replay"

    def test_游标早于留存窗口判snapshot(self, ledger):
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk"})
        ledger.appendEvent("pair-1", 1, {"type": "chat:done"})
        # 模拟老化：删除窗口前的帧（正式老化由 appendEvent 的保留窗口触发）
        with ledger._lock, ledger._conn:
            ledger._conn.execute("DELETE FROM mobile_ws_events WHERE seq = ?", (s1,))
            ledger._conn.commit()
        decision = ledger.resolveResume("pair-1", 0)
        assert decision.mode == "snapshot"
        assert decision.reason == "cursor_pruned"

    def test_预算耗尽判snapshot(self, ledger):
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk"})
        budget = ReplayByteBudget(1)
        budget.feed(1)
        assert ledger.resolveResume("pair-1", s1 - 1, budget=budget).mode == "snapshot"

    def test_他设备账目不串窗口(self, ledger):
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk"})
        ledger.appendEvent("pair-2", 1, {"type": "chat:chunk"})
        # pair-2 的帧不参与 pair-1 的窗口判定
        assert ledger.resolveResume("pair-1", s1).mode == "replay"


class TestMobileWsSyncResumeWiring:
    """端点接线：sync_resume 按单源决策走 replay / snapshot 两路。"""

    @pytest.fixture()
    def wsClient(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api import mobile_ws_ledger as wsledger
        from neurova.api.endpoints import mobile_pairing as mobile_ep

        monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger.db"))
        wsledger.resetMobileWsLedger()
        mobile_ep._pairing_codes.clear()
        mobile_ep._ws_connections.clear()
        monkeypatch.setitem(
            mobile_ep._pairing_codes,
            "MOBILE-CODE-1",
            {"status": "confirmed", "user_id": "u-drive", "pairing_id": "pair-drive"},
        )
        # 设备注册表落库面打桩：本卡只验续传决策路由，不验注册表持久化
        stubRegistry = SimpleNamespace(
            isAdmissible=lambda pairing_id, epoch: True,
            recordActivity=lambda pairing_id: None,
        )
        monkeypatch.setattr(mobile_ep, "getDeviceRegistry", lambda: stubRegistry)

        app = FastAPI()
        app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
        client = TestClient(app)
        client.wsledger = wsledger  # type: ignore[attr-defined]
        yield client
        wsledger.resetMobileWsLedger()

    def test_游标过旧下发快照重同步通告(self, wsClient):
        store = wsClient.wsledger.getMobileWsLedger()
        store.appendEvent("pair-drive", 1, {"type": "chat:chunk", "text": "a"})
        store.appendEvent("pair-drive", 1, {"type": "chat:done"})
        with store._lock, store._conn:
            store._conn.execute("DELETE FROM mobile_ws_events WHERE frame_type = 'chat:chunk'")
            store._conn.commit()
        expectedHead = store.lastSeq("pair-drive")
        with wsClient.websocket_connect("/api/v1/mobile/ws?code=MOBILE-CODE-1") as ws:
            ws.send_json({"type": "sync_resume", "last_seq": 0})
            frame = json.loads(ws.receive_text())
        assert frame["type"] == "sync_snapshot_required"
        assert frame["reason"] == "cursor_pruned"
        # 通告帧自身也走"先落账再发送"通道（会再占一个 seq），故取连前头
        assert frame["head_seq"] == expectedHead

    def test_游标有效仍走账本重放(self, wsClient):
        store = wsClient.wsledger.getMobileWsLedger()
        s1 = store.appendEvent("pair-drive", 1, {"type": "chat:chunk", "text": "a"})
        s2 = store.appendEvent("pair-drive", 1, {"type": "chat:done"})
        with wsClient.websocket_connect("/api/v1/mobile/ws?code=MOBILE-CODE-1") as ws:
            ws.send_json({"type": "sync_resume", "last_seq": s1})
            frame = json.loads(ws.receive_text())
        assert frame.get("replay") is True
        assert frame["seq"] == s2
        assert frame["type"] == "chat:done"
