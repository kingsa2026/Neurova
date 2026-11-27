# -*- coding: utf-8 -*-
"""D3 scope 端点接线测试：mobile sync_resume → 账本订阅范围（G4 能力的最后一段接线）。

验收判据（D3 卡）：
1. 缺省不传 scope → 行为与改前逐字一致（按游标全量补发，回归钉）；
2. 传 session/thread scope → 范围内帧必达、范围外帧 fail-closed 不下发；
3. 非法 scope → 400 形态诚实拒绝（error 帧 code=invalid_scope），不落账；
4. 越权 scope_key（与本设备账本归属不符）→ 403 形态拒绝，且不登记订阅；
5. 订阅生命周期：sync_resume 登记生效、连接断开即注销、重连后未再订阅走全量。

夹具形态对齐 test_mobile_ws_remote_driving.py：tmp 库 + 单例重置 + 已确认配对码
接 WS；在册设备库/限流桶由 tests/conftest.py 的 _isolateMobileDeviceRegistry 隔离。
"""
import json
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import mobile_ws_ledger as wsledger
from neurova.api.endpoints import mobile_pairing as mobile_ep

PAIRING_CODE = "SCOPE-CODE-1"
OWNER = "u-scope"
PAIRING_ID = "pair-scope"


@pytest.fixture(autouse=True)
def _freshWsLedger(tmp_path, monkeypatch):
    """移动 WS 账本单例逐测重置（tmp 库）：订阅登记是进程内内存态，不跨用例泄漏。"""
    monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger_scope.db"))
    wsledger.resetMobileWsLedger()
    yield
    wsledger.resetMobileWsLedger()


@pytest.fixture()
def wsClient(monkeypatch):
    """挂载移动配对路由 + 一条已确认配对记录（凭 code 接入 WS）。"""
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": PAIRING_ID,
         "expires_at": time.time() + 3600},
    )
    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    return TestClient(app)


def _ledger() -> wsledger.MobileWsLedger:
    return wsledger.getMobileWsLedger()


def _seed(ledger: wsledger.MobileWsLedger, frame: Dict[str, Any]) -> int:
    """直接落账一帧（epoch 仅留档用，重放判定只看 pairing_id + seq）。"""
    return ledger.appendEvent(PAIRING_ID, 1, frame)


def _open(client: TestClient):
    # 配对码生产语义为一次性消费；多连接用例显式重置为新的已确认码。
    mobile_ep._pairing_codes[PAIRING_CODE]["status"] = "confirmed"
    return client.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}")


def _resume(ws, **extra: Any) -> None:
    ws.send_json({"type": "sync_resume", "last_seq": 0, **extra})


def _read(ws, count: int) -> List[Dict[str, Any]]:
    return [json.loads(ws.receive_text()) for _ in range(count)]


def _assertQuietAfterReplay(ws) -> None:
    """哨兵：补发批次结束后发 ping，下一帧必须是 pong——若范围外帧被错误
    下发，会先于 pong 到达，断言即红（避免"多读一帧才知道"的挂死式失败）。"""
    ws.send_json({"type": "ping"})
    frame = json.loads(ws.receive_text())
    assert frame.get("type") == "pong", f"补发批次后混入了额外帧：{frame}"


def _awaitUnsubscribed(timeoutSeconds: float = 5.0) -> None:
    """等连接收尾的注销落地（断连注销是正确生产行为，测试等它完成再断言）。"""
    deadline = time.time() + timeoutSeconds
    while time.time() < deadline and _ledger().subscriptionOf(PAIRING_ID) is not None:
        time.sleep(0.02)
    assert _ledger().subscriptionOf(PAIRING_ID) is None, "断连后订阅应被注销"


class TestSyncResumeScope接线:
    """sync_resume 的可选订阅范围：缺省零影响、按范围过滤、非法/越权诚实拒绝。"""

    def test_缺省不传scope_行为与改前一致(self, wsClient):
        """回归钉：不传 scope 时按游标全量补发（含无归属帧），与改前逐字一致。"""
        ledger = _ledger()
        seqs = [
            _seed(ledger, {"type": "chat:chunk", "session_id": "s1", "content": "a"}),
            _seed(ledger, {"type": "chat:chunk", "session_id": "s2", "content": "b"}),
            _seed(ledger, {"type": "notice"}),
        ]
        with _open(wsClient) as ws:
            _resume(ws)
            frames = _read(ws, 3)
            assert [f["seq"] for f in frames] == seqs, "缺省补发不得丢帧、不得改序"
            assert all(f.get("replay") is True for f in frames)
            assert frames[2]["type"] == "notice", "无归属帧在缺省路径照常下发"
            _assertQuietAfterReplay(ws)

    def test_session范围_范围内必达范围外不下发(self, wsClient):
        ledger = _ledger()
        s1Seqs = [
            _seed(ledger, {"type": "chat:chunk", "session_id": "s1", "content": "a"}),
            _seed(ledger, {"type": "chat:chunk", "session_id": "s1", "content": "b"}),
        ]
        _seed(ledger, {"type": "chat:chunk", "session_id": "s2", "content": "c"})
        _seed(ledger, {"type": "notice"})
        with _open(wsClient) as ws:
            _resume(ws, scope="session", scope_key="s1")
            frames = _read(ws, 2)
            assert [f["seq"] for f in frames] == s1Seqs, "范围内帧按原 seq 必达"
            assert all(f.get("session_id") == "s1" for f in frames)
            assert all(f.get("replay") is True for f in frames)
            _assertQuietAfterReplay(ws), "s2 与无归属帧必须被扣下"

    def test_session范围_游标与范围叠加不漏范围内帧(self, wsClient):
        """游标语义保持：scope 过滤只收紧下发集合，游标之后范围内的帧仍必达。"""
        ledger = _ledger()
        _seed(ledger, {"type": "chat:chunk", "session_id": "s1"})
        s2Seq = _seed(ledger, {"type": "chat:chunk", "session_id": "s2"})
        laterSeq = _seed(ledger, {"type": "chat:done", "session_id": "s1"})
        _seed(ledger, {"type": "chat:chunk", "session_id": "s2"})
        with _open(wsClient) as ws:
            ws.send_json({"type": "sync_resume", "last_seq": s2Seq,
                          "scope": "session", "scope_key": "s1"})
            frames = _read(ws, 1)
            assert [f["seq"] for f in frames] == [laterSeq]
            _assertQuietAfterReplay(ws), "游标后的 s2 帧不得混入 s1 订阅"

    def test_非法scope名_400诚实拒绝(self, wsClient):
        _seed(_ledger(), {"type": "chat:chunk", "session_id": "s1"})
        with _open(wsClient) as ws:
            _resume(ws, scope="everything", scope_key="x")
            frame = _read(ws, 1)[0]
            assert frame.get("type") == "error", frame
            assert frame.get("code") == "invalid_scope", frame
            assert frame.get("status") == 400, frame
            _assertQuietAfterReplay(ws), "拒绝后不得再下发任何补发帧"
        assert _ledger().subscriptionOf(PAIRING_ID) is None, "非法范围不得登记"

    def test_session范围缺scope_key_400诚实拒绝(self, wsClient):
        _seed(_ledger(), {"type": "chat:chunk", "session_id": "s1"})
        with _open(wsClient) as ws:
            _resume(ws, scope="session")
            frame = _read(ws, 1)[0]
            assert frame.get("type") == "error", frame
            assert frame.get("code") == "invalid_scope", frame
            assert frame.get("status") == 400, frame
            _assertQuietAfterReplay(ws)
        assert _ledger().subscriptionOf(PAIRING_ID) is None

    def test_越权scope_key_403拒绝且不登记(self, wsClient):
        """scope_key 不在本设备账本归属内（他会话/探测键）→ 拒绝，不泄露存在性。"""
        _seed(_ledger(), {"type": "chat:chunk", "session_id": "s1"})
        with _open(wsClient) as ws:
            _resume(ws, scope="session", scope_key="s-ghost")
            frame = _read(ws, 1)[0]
            assert frame.get("type") == "error", frame
            assert frame.get("code") == "scope_forbidden", frame
            assert frame.get("status") == 403, frame
            _assertQuietAfterReplay(ws), "越权订阅不得下发任何帧"
        assert _ledger().subscriptionOf(PAIRING_ID) is None, "被拒订阅不得留下登记"

    def test_thread范围_按请求显式键过滤(self, wsClient):
        ledger = _ledger()
        t1Seqs = [
            _seed(ledger, {"type": "chat:chunk", "thread_id": "t1"}),
            _seed(ledger, {"type": "chat:done", "thread_id": "t1"}),
        ]
        _seed(ledger, {"type": "chat:chunk", "thread_id": "t2"})
        with _open(wsClient) as ws:
            _resume(ws, scope="thread", scope_key="t1")
            frames = _read(ws, 2)
            assert [f["seq"] for f in frames] == t1Seqs
            assert all(f.get("thread_id") == "t1" for f in frames)
            _assertQuietAfterReplay(ws), "t2 的帧不得混入 t1 订阅"
            sub = _ledger().subscriptionOf(PAIRING_ID)
            assert sub is not None and sub.scope == "thread" and sub.scope_key == "t1"
        _awaitUnsubscribed()

    def test_global范围_全收本设备帧并登记(self, wsClient):
        ledger = _ledger()
        seqs = [
            _seed(ledger, {"type": "chat:chunk", "session_id": "s1"}),
            _seed(ledger, {"type": "notice"}),
        ]
        with _open(wsClient) as ws:
            _resume(ws, scope="global")
            frames = _read(ws, 2)
            assert [f["seq"] for f in frames] == seqs, "global 订阅收本设备全部帧"
            _assertQuietAfterReplay(ws)
            sub = _ledger().subscriptionOf(PAIRING_ID)
            assert sub is not None and sub.scope == "global" and sub.scope_key == ""
        _awaitUnsubscribed()

    def test_订阅生命周期_登记生效_断连注销_重连默认全量(self, wsClient):
        """登记 →（同连接）缺省续传回落登记范围 → 断连注销 → 重连未订阅走全量。"""
        ledger = _ledger()
        s1Seqs = [
            _seed(ledger, {"type": "chat:chunk", "session_id": "s1"}),
            _seed(ledger, {"type": "chat:done", "session_id": "s1"}),
        ]
        _seed(ledger, {"type": "chat:chunk", "session_id": "s2"})
        _seed(ledger, {"type": "chat:chunk", "session_id": "s2"})
        allSeqs = [f["seq"] for f in ledger.replaySince(PAIRING_ID, 0)]

        with _open(wsClient) as ws:
            _resume(ws, scope="session", scope_key="s1")
            frames = _read(ws, 2)
            assert [f["seq"] for f in frames] == s1Seqs
            sub = _ledger().subscriptionOf(PAIRING_ID)
            assert sub is not None and sub.scope == "session" and sub.scope_key == "s1"

            # 同连接内缺省续传：回落到已登记订阅（账本单源语义），仍只发 s1
            _resume(ws)
            frames = _read(ws, 2)
            assert [f["seq"] for f in frames] == s1Seqs
            _assertQuietAfterReplay(ws)

        # 连接关闭即注销（订阅是连接级内存态，重连由客户端重新订阅）
        _awaitUnsubscribed()

        # 重连后未再订阅的既有客户端：回到改前行为，全量按游标补发
        with _open(wsClient) as ws:
            _resume(ws)
            frames = _read(ws, len(allSeqs))
            assert [f["seq"] for f in frames] == allSeqs, "未订阅重连必须与改前全量一致"
            _assertQuietAfterReplay(ws)
