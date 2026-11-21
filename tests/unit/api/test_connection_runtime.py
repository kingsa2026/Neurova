# -*- coding: utf-8 -*-
"""G4 多端连接运行时单源（neurova/api/connection_runtime.py）行为钉子。

钉四条契约（T3 形态：单写者服务器 + 按需订阅 + 共享连接运行时）：
1. 常量单源：心跳间隔 15s / 重放窗口 1 天（对齐 A2 事件库保留窗）/
   订阅范围枚举，三端（PC/鸿蒙/安卓）只有一个出处；
2. env 覆盖与非法回落：NEUROVA_HEARTBEAT_INTERVAL_S / NEUROVA_REPLAY_WINDOW_S
   合法值生效，缺省/非法/非正数一律回落默认（fail-closed）；
3. 订阅范围（按需订阅——"看一个线程不付全部线程的账"）：scope 解析校验 +
   inScope 归属判定，解析失败的帧 fail-closed 不下发；
4. 接线回归：realtime_push 心跳缺省从单源取（现值 15s 不变）；
   mobile_ws_ledger 订阅/重放路径按范围过滤（只收紧不放宽）。
"""
import asyncio
import json

import pytest

from neurova.api.connection_runtime import (
    CONNECTION_RUNTIME_VERSION,
    HEARTBEAT_INTERVAL_S,
    REPLAY_WINDOW_S,
    SUBSCRIPTION_SCOPES,
    SubscriptionScope,
    describeForClients,
    heartbeat_interval_s,
    inScope,
    parseSubscriptionScope,
    replay_window_s,
)


class Test单源常量:
    """三端共用的连接运行时常量只有一处出处。"""

    def test_心跳间隔常量为15秒(self):
        assert HEARTBEAT_INTERVAL_S == 15.0

    def test_重放窗口对齐事件库一天保留(self):
        from neurova.agent.swarm_event_store import DEFAULT_KEEP_WINDOW_S

        assert REPLAY_WINDOW_S == 86400.0
        assert REPLAY_WINDOW_S == float(DEFAULT_KEEP_WINDOW_S), "与 A2 事件库 1 天保留同口径"

    def test_订阅范围枚举(self):
        assert SUBSCRIPTION_SCOPES == ("session", "thread", "global")


class TestEnv覆盖与非法回落:
    """env 可覆盖，非法一律回落默认（fail-closed，不抛错不带病运行）。"""

    def test_缺省取常量(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_HEARTBEAT_INTERVAL_S", raising=False)
        monkeypatch.delenv("NEUROVA_REPLAY_WINDOW_S", raising=False)
        assert heartbeat_interval_s() == 15.0
        assert replay_window_s() == 86400.0

    def test_合法env覆盖生效(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", "5")
        monkeypatch.setenv("NEUROVA_REPLAY_WINDOW_S", "3600")
        assert heartbeat_interval_s() == 5.0
        assert replay_window_s() == 3600.0

    def test_非法env回落默认(self, monkeypatch):
        for bad in ("abc", "-1", "0", "", "  ", "nan", "inf"):
            monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", bad)
            monkeypatch.setenv("NEUROVA_REPLAY_WINDOW_S", bad)
            assert heartbeat_interval_s() == 15.0, f"heartbeat env={bad!r} 应回落默认"
            assert replay_window_s() == 86400.0, f"replay env={bad!r} 应回落默认"

    def test_带空白与科学计数法的合法值(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", " 2.5 ")
        monkeypatch.setenv("NEUROVA_REPLAY_WINDOW_S", "1e3")
        assert heartbeat_interval_s() == 2.5
        assert replay_window_s() == 1000.0


class Test订阅范围解析:
    """scope + scope_key 的解析与校验（fail-closed：非法即拒）。"""

    def test_合法范围解析(self):
        assert parseSubscriptionScope("session", "s1") == SubscriptionScope("session", "s1")
        assert parseSubscriptionScope("thread", "t1") == SubscriptionScope("thread", "t1")
        assert parseSubscriptionScope("global") == SubscriptionScope("global", "")

    def test_范围名大小写与空白宽容(self):
        assert parseSubscriptionScope(" Session ", "s1").scope == "session"

    def test_非法范围名拒绝(self):
        with pytest.raises(ValueError):
            parseSubscriptionScope("agent", "a1")
        with pytest.raises(ValueError):
            parseSubscriptionScope("", "s1")
        with pytest.raises(ValueError):
            parseSubscriptionScope(None, "s1")

    def test_会话与线程范围缺scope_key拒绝(self):
        with pytest.raises(ValueError):
            parseSubscriptionScope("session", "")
        with pytest.raises(ValueError):
            parseSubscriptionScope("thread", "  ")
        # global 不需要 scope_key
        assert parseSubscriptionScope("global", "").isGlobal


class TestInScope归属判定:
    """帧按 session_id/thread_id 归属判定；global 全收；解析失败 fail-closed。"""

    def test_global全收(self):
        sub = parseSubscriptionScope("global")
        assert inScope({"type": "chat:chunk", "session_id": "s1"}, sub)
        assert inScope({"type": "chat:chunk", "session_id": "s2"}, sub)
        assert inScope({"type": "chat:chunk"}, sub), "global 对无法归属的帧也放行"

    def test_session范围按session_id判定(self):
        sub = parseSubscriptionScope("session", "s1")
        assert inScope({"session_id": "s1"}, sub)
        assert not inScope({"session_id": "s2"}, sub)

    def test_thread范围按thread_id判定(self):
        sub = parseSubscriptionScope("thread", "t1")
        assert inScope({"thread_id": "t1"}, sub)
        assert not inScope({"thread_id": "t2"}, sub)
        assert not inScope({"session_id": "t1"}, sub), "session_id 不能冒充 thread 归属"

    def test_解析失败的帧fail_closed不下发(self):
        sub = parseSubscriptionScope("session", "s1")
        assert not inScope({}, sub), "缺 session_id 的帧不下发"
        assert not inScope({"session_id": ""}, sub), "空 session_id 不下发"
        assert not inScope({"session_id": "   "}, sub), "纯空白 session_id 不下发"
        assert not inScope({"session_id": 123}, sub), "非字符串 session_id 不下发"
        assert not inScope("not-a-dict", sub), "非 dict 帧不下发"
        assert not inScope(None, sub), "None 帧不下发"

    def test_订阅对象非法时fail_closed(self):
        assert not inScope({"session_id": "s1"}, None), "无有效订阅不下发"
        assert not inScope({"session_id": "s1"}, ("session", "s1")), "裸元组不是合法订阅"

    def test_订阅对象不可变(self):
        sub = parseSubscriptionScope("session", "s1")
        with pytest.raises(Exception):
            sub.scope = "global"


class Test客户端契约描述:
    """describeForClients：握手/订阅应答携带的三端契约描述。"""

    def test_描述含版本心跳退避重放与订阅范围(self):
        desc = describeForClients()
        assert isinstance(desc, dict)
        assert desc["version"] == CONNECTION_RUNTIME_VERSION
        assert desc["heartbeat"]["interval_s"] == heartbeat_interval_s()
        assert desc["replay"]["window_s"] == replay_window_s()
        assert desc["subscription"]["scopes"] == list(SUBSCRIPTION_SCOPES)
        # 退避语义引用 subscription_resume 单源常量，不另抄一份
        from neurova.api.subscription_resume import (
            RECONNECT_BACKOFF_BASE_S,
            RECONNECT_BACKOFF_CAP_S,
            RECONNECT_BACKOFF_JITTER_FRACTION,
        )

        assert desc["reconnect"]["backoff_base_s"] == RECONNECT_BACKOFF_BASE_S
        assert desc["reconnect"]["backoff_cap_s"] == RECONNECT_BACKOFF_CAP_S
        assert desc["reconnect"]["backoff_jitter"] == RECONNECT_BACKOFF_JITTER_FRACTION

    def test_描述随env覆盖联动(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", "7")
        monkeypatch.setenv("NEUROVA_REPLAY_WINDOW_S", "600")
        desc = describeForClients()
        assert desc["heartbeat"]["interval_s"] == 7.0
        assert desc["replay"]["window_s"] == 600.0


# ── realtime_push 接线回归 ────────────────────────────────────────────


def _render(frame):
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


class _TimeoutCaptureFeed:
    """记录 nextFrame 收到的 timeout（即生效心跳间隔），首次调用即关源收尾。"""

    def __init__(self):
        self.timeouts = []

    def snapshot(self):
        return []

    def frameKey(self, frame):
        return frame.get("seq")

    def isTerminal(self, frame):
        return False

    async def nextFrame(self, afterKey, timeout):
        from neurova.api.realtime_push import FEED_EXHAUSTED

        self.timeouts.append(timeout)
        return FEED_EXHAUSTED


def _collect(stream, maxChunks=50):
    async def _run():
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
            if len(chunks) >= maxChunks:
                break
        return chunks

    return asyncio.run(_run())


class TestRealtimePush心跳单源接线:
    """ssePushStream 心跳缺省改从 connection_runtime 取（现值 15s 行为不变）。"""

    def test_缺省心跳间隔来自单源(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", "0.05")
        feed = _TimeoutCaptureFeed()
        _collect(_pushStream(feed))
        assert feed.timeouts == [0.05], "缺省心跳间隔必须经 connection_runtime 解析 env"

    def test_显式心跳间隔仍被尊重(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_HEARTBEAT_INTERVAL_S", raising=False)
        feed = _TimeoutCaptureFeed()
        _collect(_pushStream(feed, heartbeatInterval=0.25))
        assert feed.timeouts == [0.25]

    def test_单源现值与改前硬编码一致(self):
        """回归钉：单源值 == realtime_push 改前签名里的 15.0，行为零差异。"""
        from neurova.api.realtime_push import DEFAULT_HEARTBEAT_INTERVAL_S

        assert DEFAULT_HEARTBEAT_INTERVAL_S == HEARTBEAT_INTERVAL_S == 15.0


def _pushStream(feed, **kwargs):
    from neurova.api.realtime_push import ssePushStream

    return ssePushStream(feed=feed, renderFrame=_render, **kwargs)


# ── mobile_ws_ledger 订阅/重放范围过滤接线 ────────────────────────────


class TestMobileLedger订阅范围过滤:
    """账本重放路径接 SubscriptionScope：只收紧不放宽（pairing 归属校验保持）。"""

    @pytest.fixture()
    def ledger(self, tmp_path):
        from neurova.api import mobile_ws_ledger

        store = mobile_ws_ledger.MobileWsLedger(db_path=tmp_path / "ws_ledger_scope.db")
        yield store
        store.close()

    def _seed(self, ledger):
        """三帧：s1 会话帧、s2 会话帧、无归属帧（如连接级通告）。"""
        ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s1"})
        ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s2"})
        ledger.appendEvent("pair-1", 1, {"type": "notice"})

    def test_未订阅时重放不过滤_行为同改前(self, ledger):
        self._seed(ledger)
        rows = ledger.replaySince("pair-1", 0)
        assert len(rows) == 3, "无订阅登记时不做范围过滤（不额外收紧既有路径）"

    def test_会话订阅只回放该会话帧(self, ledger):
        self._seed(ledger)
        ledger.subscribe("pair-1", "session", "s1")
        rows = ledger.replaySince("pair-1", 0)
        types = [(r["frame"].get("type"), r["frame"].get("session_id")) for r in rows]
        assert types == [("chat:chunk", "s1")], "只下发 s1 的帧；s2 与无归属帧 fail-closed 扣下"

    def test_线程订阅按thread_id过滤(self, ledger):
        ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "thread_id": "t1"})
        ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "thread_id": "t2"})
        ledger.subscribe("pair-1", "thread", "t1")
        rows = ledger.replaySince("pair-1", 0)
        assert [r["frame"]["thread_id"] for r in rows] == ["t1"]

    def test_global订阅全收(self, ledger):
        self._seed(ledger)
        ledger.subscribe("pair-1", "global")
        assert len(ledger.replaySince("pair-1", 0)) == 3

    def test_显式scope参数覆盖已登记订阅(self, ledger):
        self._seed(ledger)
        ledger.subscribe("pair-1", "session", "s1")
        rows = ledger.replaySince("pair-1", 0, scope=parseSubscriptionScope("session", "s2"))
        assert [r["frame"]["session_id"] for r in rows] == ["s2"]

    def test_退订后恢复不过滤(self, ledger):
        self._seed(ledger)
        ledger.subscribe("pair-1", "session", "s1")
        ledger.unsubscribe("pair-1")
        assert len(ledger.replaySince("pair-1", 0)) == 3

    def test_非法订阅范围拒绝(self, ledger):
        with pytest.raises(ValueError):
            ledger.subscribe("pair-1", "everything", "x")

    def test_订阅查询(self, ledger):
        assert ledger.subscriptionOf("pair-1") is None
        sub = ledger.subscribe("pair-1", "session", "s1")
        assert ledger.subscriptionOf("pair-1") == sub
        assert isinstance(sub, SubscriptionScope)

    def test_设备归属校验不放宽(self, ledger):
        """scope 过滤只做加法：他设备的帧任何时候都不因订阅而放行。"""
        ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s1"})
        pair2Seq = ledger.appendEvent("pair-2", 1, {"type": "chat:chunk", "session_id": "s1"})
        ledger.subscribe("pair-1", "global")
        rows = ledger.replaySince("pair-1", 0)
        seqs = [r["seq"] for r in rows]
        assert pair2Seq not in seqs, "pair-2 的帧不得混入 pair-1 的重放"
        assert len(seqs) == 1, "global 订阅也只收本设备帧"

    def test_重放游标语义不受过滤影响(self, ledger):
        """被过滤帧不外发，但 seq 单调性保持——客户端按最后收到的 seq 续传不漏。"""
        s1 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s1"})
        s2 = ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s2"})
        s3 = ledger.appendEvent("pair-1", 1, {"type": "chat:done", "session_id": "s1"})
        ledger.subscribe("pair-1", "session", "s1")
        rows = ledger.replaySince("pair-1", 0)
        assert [r["seq"] for r in rows] == [s1, s3]
        # 从被过滤帧之后续传，仍能拿到后续同会话帧
        rows2 = ledger.replaySince("pair-1", s2)
        assert [r["seq"] for r in rows2] == [s3]
