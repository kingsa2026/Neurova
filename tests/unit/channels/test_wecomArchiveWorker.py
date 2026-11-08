# -*- coding: utf-8 -*-
"""批 C7c（第一块）：落库前白名单过滤＋常驻增量 worker＋水位落后读数。

方案出处：`docs/specs/2026-11-07-wecom-chat-archive-history-source-plan.md` §8/§13-1。

判据：
- **白名单落库前过滤**（§13-1：隐私缓解在通道层落库前，不是摄取后再删）：
  roomAllowlist 群白名单 / userAllowlist 参与者白名单；都给＝AND；都空＝不过滤
  （白名单是隐私手段不是功能开关）；过滤数进读数，**不静默丢**；
- **backfill 默认开**（§8 更正后语义）：水位初始 0＝首轮即从 seq=0 拉到当前水位，
  不存在「要不要回溯」的开关——5 天窗口下不拉就永久丢；
- **常驻 worker**：单轮批量上限自我节流（与官方 4000 次/分钟两回事）；任一批失败
  整轮抛出、下轮从水位续拉；凭据未就绪轮跳过并给原因；
- **水位落后读数**（§8：health 须能报「水位落后多久」）：≥5 天点名「不可取回」，
  窗口内只报天数，无时间戳不编。

夹具＝真 RSA-2048 密钥对＋假 SDK（同 reader 档）＋真 ArchiveProjectionStore
（NEUROVA_WECOM_ARCHIVE_ENV 注入 tmp）；渠道装配面用假适配器替身（config.extra 真
字典走真 archiveReadiness 校验），manager 注入于 monkeypatch。
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from neurova.channels import wecom_archive
from neurova.channels.wecom_archive import (
    ARCHIVE_ROOM_ALLOWLIST_FIELD,
    ARCHIVE_USER_ALLOWLIST_FIELD,
    ARCHIVE_WINDOW_DAYS,
    ArchiveConfigError,
    applyArchiveAllowlist,
    runArchiveWorkerCycle,
    watermarkLagReading,
)

# ── 夹具 ─────────────────────────────────────────────────────


class FakeArchiveSdk:
    def __init__(self, rowsBySeq=None):
        self._rows = dict(rowsBySeq or {})
        self.calls = []

    def getChatData(self, seq, limit, timeout=10):
        self.calls.append((int(seq), int(limit)))
        return [self._rows[s] for s in sorted(self._rows) if s > int(seq)][: int(limit)]

    def decryptData(self, encryptKey: bytes, encryptMsg: bytes) -> bytes:
        return encryptMsg

    def close(self):
        return None


def _rsaPem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _rawRow(seq, plainMsg, publicKey, ver="v1"):
    sealed = publicKey.encrypt(b"0123456789abcdef0123456789abcdef", padding.PKCS1v15())
    return {
        "seq": seq, "msgid": "msg_%d" % seq, "publickey_ver": ver,
        "encrypt_random_key": base64.b64encode(sealed).decode("ascii"),
        "encrypt_chat_msg": base64.b64encode(
            json.dumps(plainMsg, ensure_ascii=False).encode("utf-8")).decode("ascii"),
    }


def _plain(seq, content=None, roomid="", msgtype="text"):
    body = {"content": content if content is not None else "消息%d" % seq}
    return {
        "msgid": "msg_%d" % seq, "action": "send", "from": "userid_a",
        "tolist": ["userid_b"], "roomid": roomid, "msgtime": 1700000000000 + seq,
        "msgtype": msgtype, "text": body if msgtype == "text" else {},
    }


def _readyContext(sdkRows=None, **extraOverrides):
    _priv, pem, pub = _rsaKeyPair()
    rows = sdkRows or {}
    return {
        "agentId": "default", "ready": True,
        "sdkPath": "unused-by-fake", "corpid": "corp_x", "secret": "s",
        "keyMap": {"v1": pem},
        "roomAllowlist": list(extraOverrides.get("roomAllowlist", [])),
        "userAllowlist": list(extraOverrides.get("userAllowlist", [])),
    }, rows, pub


def _rsaKeyPair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return key, pem, key.public_key()


@pytest.fixture()
def archiveEnv(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_CHANNEL_ARCHIVE_DB", str(tmp_path / "archive.db"))
    return tmp_path / "archive.db"


def _patchContext(monkeypatch, context):
    monkeypatch.setattr(wecom_archive, "_archiveWorkerContexts",
                        lambda agentId="default": [context])


# ── 白名单过滤 ───────────────────────────────────────────────


def test_room_allowlist_filters_before_projection():
    rows = [{"roomid": "wrKeep", "from_id": "a", "tolist": "[]"},
            {"roomid": "wrDrop", "from_id": "a", "tolist": "[]"},
            {"roomid": "", "from_id": "a", "tolist": '["b"]'}]
    kept, filtered = applyArchiveAllowlist(rows, ["wrKeep"], [])
    assert [r["roomid"] for r in kept] == ["wrKeep"], (
        "名单外群与非群聊都应被过滤——白名单非空时群聊只保留名单内的")
    assert filtered == 2, "过滤数必须可读（不静默丢）"


def test_user_allowlist_matches_participants():
    rows = [{"roomid": "", "from_id": "alice", "tolist": '["bob"]'},
            {"roomid": "", "from_id": "eve", "tolist": '["mallory"]'},
            {"roomid": "wr1", "from_id": "alice", "tolist": '["carol", "bob"]'},
            {"roomid": "wr1", "from_id": "alice", "tolist": '["carol"]'}]
    kept, filtered = applyArchiveAllowlist(rows, [], ["bob"])
    assert len(kept) == 2, (
        "参与者白名单：from 或 tolist 任一命中即保留（alice→bob；群聊含 bob 也命中）")
    assert filtered == 2, "无交集的行被过滤且计数如实"


def test_both_allowlists_are_and_semantics():
    rows = [{"roomid": "wrKeep", "from_id": "alice", "tolist": '["bob"]'},
            {"roomid": "wrKeep", "from_id": "eve", "tolist": '["mallory"]'}]
    kept, _ = applyArchiveAllowlist(rows, ["wrKeep"], ["bob"])
    assert len(kept) == 1, "两名单同给＝同时满足（AND）"


def test_empty_allowlists_pass_everything_through():
    rows = [{"roomid": "wrAny", "from_id": "a", "tolist": "[]"}]
    kept, filtered = applyArchiveAllowlist(rows, [], [])
    assert kept == rows and filtered == 0, (
        "白名单是隐私缓解手段不是功能开关：都空＝不过滤")


def test_allowlist_config_must_be_string_lists():
    with pytest.raises(ArchiveConfigError):
        wecom_archive.validateArchiveExtra({ARCHIVE_ROOM_ALLOWLIST_FIELD: "wr1"})
    with pytest.raises(ArchiveConfigError):
        wecom_archive.validateArchiveExtra(
            {ARCHIVE_USER_ALLOWLIST_FIELD: ["ok", 42]})


# ── 常驻 worker ──────────────────────────────────────────────


def test_worker_cycle_backfills_from_zero_and_converges(archiveEnv, monkeypatch):
    """backfill 默认开：水位 0＝首轮从 seq=0 拉到当前水位；多页收敛后二轮空转。"""
    _priv, pem, pub = _rsaKeyPair()
    sdkRows = {seq: _rawRow(seq, _plain(seq), pub) for seq in range(1, 9)}
    context, _, _pub = _readyContext()
    context["keyMap"] = {"v1": pem}
    _patchContext(monkeypatch, context)
    sdk = FakeArchiveSdk(sdkRows)

    first = runArchiveWorkerCycle(sdkFactory=lambda: sdk,
                                  batchesPerCycle=5, batchLimit=3)
    assert first["status"] == "ok"
    assert first["written"] == 8, "8 行 3/页 → 3 批收敛（分页拉取非一次吞）"
    assert first["watermark"] == 8
    assert sdk.calls[0] == (0, 3), "首轮从水位 0 起（backfill 默认开，§8 更正语义）"

    second = runArchiveWorkerCycle(sdkFactory=lambda: sdk,
                                   batchesPerCycle=5, batchLimit=3)
    assert second["written"] == 0 and second["watermark"] == 8, (
        "水位收敛后单轮空转（幂等，不重拉）")


def test_worker_cycle_applies_allowlist_before_projection(archiveEnv, monkeypatch):
    _priv, pem, pub = _rsaKeyPair()
    sdkRows = {
        1: _rawRow(1, _plain(1, roomid="wrKeep"), pub),
        2: _rawRow(2, _plain(2, roomid="wrDrop"), pub),
    }
    context, _, _ = _readyContext(roomAllowlist=["wrKeep"])
    context["keyMap"] = {"v1": pem}
    _patchContext(monkeypatch, context)
    outcome = runArchiveWorkerCycle(sdkFactory=lambda: FakeArchiveSdk(sdkRows))
    assert outcome["written"] == 1 and outcome["filtered"] == 1, (
        "白名单在落库前过滤：名单外群不进投影，但过滤数如实可读")
    assert outcome["watermark"] == 2, "被过滤的行也推进水位（不重拉）"
    store = wecom_archive.ArchiveProjectionStore(archiveEnv)
    try:
        sendRows, _, _ = store.querySendRows(0, 10)
        assert [r["roomid"] for r in sendRows] == ["wrKeep"]
    finally:
        store.close()


def test_worker_cycle_batch_failure_aborts_round(archiveEnv, monkeypatch):
    """任一批失败整轮抛出（§5 不落半行）；下轮从已提交水位续拉。"""
    _priv, pem, pub = _rsaKeyPair()
    context, _, _ = _readyContext()
    context["keyMap"] = {"v1": pem}
    _patchContext(monkeypatch, context)

    class HalfBrokenSdk(FakeArchiveSdk):
        def getChatData(self, seq, limit, timeout=10):
            if int(seq) >= 2:
                raise wecom_archive.ArchiveSdkError("GetChatData 失败 ret=7")
            return super().getChatData(seq, limit, timeout=timeout)

    sdk = HalfBrokenSdk({seq: _rawRow(seq, _plain(seq), pub) for seq in (1, 2, 3)})
    with pytest.raises(wecom_archive.ArchiveSdkError):
        runArchiveWorkerCycle(sdkFactory=lambda: sdk, batchesPerCycle=5, batchLimit=2)
    store = wecom_archive.ArchiveProjectionStore(archiveEnv)
    try:
        # 第一批（行 1,2）成功提交水位 2；第二批在拉取即抛——零行落库（不落半行）
        assert store.watermark() == 2, "成功批推进水位；失败批零落库"
        sendRows, _, _ = store.querySendRows(0, 10)
        assert [r["seq"] for r in sendRows] == [1, 2]
    finally:
        store.close()


def test_worker_cycle_skips_when_credentials_not_ready(archiveEnv, monkeypatch):
    _patchContext(monkeypatch, {"ready": False, "reason": "会话存档专用 Secret 未配置"})
    outcome = runArchiveWorkerCycle(sdkFactory=lambda: FakeArchiveSdk({}))
    assert outcome == {"status": "skipped", "reason": "会话存档专用 Secret 未配置"}


def test_worker_context_reads_real_adapter_config(tmp_path, monkeypatch):
    """上下文构建走真 archiveReadiness 判据：配置齐 → ready 且 keyMap 解引用。"""
    pemPath = tmp_path / "key.pem"
    pemPath.write_bytes(_rsaPem())
    loadable = Path("C:/Windows/System32/kernel32.dll") if Path(
        "C:/Windows/System32/kernel32.dll").is_file() else None
    if loadable is None:
        pytest.skip("无本机可加载原生库件可作探针")

    class FakeAdapter:
        class config:  # noqa: N801 - 命名跟随被替身形状
            extra = {
                "corpid": "corp_x", "app_id": "app_x",
                wecom_archive.ARCHIVE_SDK_PATH_FIELD: str(loadable),
                wecom_archive.ARCHIVE_SECRET_ENV_FIELD: "NEUROVA_UNIT_C7C_SECRET",
                wecom_archive.ARCHIVE_PRIVATE_KEYS_FIELD: {"v1": str(pemPath)},
            }

    class FakeManager:
        def get_adapter(self, channelType, agent_id="default"):
            return FakeAdapter() if channelType == "wecom" else None

    monkeypatch.setenv("NEUROVA_UNIT_C7C_SECRET", "secret-value")
    monkeypatch.setattr("neurova.channels.manager.get_channel_manager",
                        lambda: FakeManager())
    contexts = wecom_archive._archiveWorkerContexts("default")
    assert len(contexts) == 1 and contexts[0]["ready"] is True
    assert contexts[0]["corpid"] == "corp_x"
    assert set(contexts[0]["keyMap"]) == {"v1"}


# ── 水位落后读数 ─────────────────────────────────────────────


def test_watermark_lag_reading():
    assert watermarkLagReading("") == "", "无时间戳不编数"
    now = dt.datetime.now(dt.timezone.utc)
    oneDay = (now - dt.timedelta(days=1)).isoformat()
    sixDays = (now - dt.timedelta(days=6)).isoformat()
    assert watermarkLagReading(oneDay) == "水位落后 1 天"
    assert "不可取回" in watermarkLagReading(sixDays), (
        "落后超 5 天窗口＝那段历史永久丢，health 必须点名")
    assert watermarkLagReading("garbage") == "", "解析不了的时间戳不编数"


def test_archive_health_names_watermark_lag(archiveEnv, monkeypatch):
    """投影面可达但水位停在 6 天前 → health 点名「不可取回」（§8 静默丢历史防线）。"""
    store = wecom_archive.ArchiveProjectionStore(archiveEnv)
    try:
        store.appendBatch([{
            "seq": 1, "msgid": "m1", "publickey_ver": "v1", "action": "send",
            "msgtype": "text", "from_id": "a", "tolist": "[]", "roomid": "",
            "msgtime_ms": 1700000000000, "text": "t", "media_ref": "",
        }], nextSeq=1)
        stale = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=ARCHIVE_WINDOW_DAYS + 1)).isoformat()
        store._conn.execute(
            "UPDATE channel_archive_state SET updated_at = ? WHERE key = 'watermark_seq'",
            (stale,))
        store._conn.commit()
    finally:
        store.close()

    monkeypatch.setattr(
        wecom_archive, "wecomArchiveReadiness",
        lambda agentId="default": wecom_archive.ArchiveReadiness(
            status="degraded", reason="会话存档原生库与凭据就绪", ready=True))
    from neurova.knowledge.enterprise.connectors_chat import ChatChannelAdapter

    adapter = ChatChannelAdapter(
        {"sourceType": "chat", "vendor": "wecom", "chatSource": "archive",
         "archiveDb": str(archiveEnv)}, "src")
    health = asyncio.run(adapter.health())
    assert health.status == "degraded"
    assert "不可取回" in health.reason, "水位落后超窗必须点名（防静默丢历史）"


def test_worker_loop_env_gate_defaults_off():
    """常驻面默认关（§8）：app 接线块受 NEUROVA_WECOM_ARCHIVE_WORKER=on 门控。"""
    from pathlib import Path

    appSource = (Path(__file__).resolve().parents[3] / "neurova" / "api" / "app.py"
                 ).read_text(encoding="utf-8")
    assert "NEUROVA_WECOM_ARCHIVE_WORKER" in appSource, "接线块缺席＝常驻面未接线"
    gate = 'os.environ.get("NEUROVA_WECOM_ARCHIVE_WORKER") or ""'
    assert gate in appSource, "门控必须缺省为空串（默认关），不许写成默认 on"
