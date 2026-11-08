# -*- coding: utf-8 -*-
"""批 C7b：通道层存档读取面——假 SDK 夹具（方案 §11 C7b 第一行 / §5 / §8）。

判据（全部红在行为断言上；假 SDK 只替「AES 半边在 SDK 内」的 DecryptData 与
网络面 GetChatData，RSA 半边用真 cryptography 密钥对走真实现）：

- **GetChatData「从 seq+1 起」**：pullArchiveBatch 把入参 seq 原样交给 SDK
  （自增一即双重推进 bug），nextSeq 取自返回行的最大 seq——跳过行也计入水位，
  否则未知 key_ver 的行会被无限重拉；
- **水位只在成功后推进**：appendBatch 单事务「落行＋推水印」，重放同批幂等
  （INSERT OR IGNORE，written=0），坏行回滚不落半行；
- **publickey_ver 未知 → 跳过并计数**（方案 §3 前置表），不猜、不抛；
- **RSA 失败显式抛**（§5），不静默落密文；
- **action 处置**：send/recall/switch 全部落投影（append-only 的诚实存档），
  recall/switch 各自计数；归一成六列行集是消费面（adapter）的事，只认 action=send；
- **msgtime 毫秒 → ISO8601 带时区**（与捕获面 timestamp.isoformat() 同形）；
- **limit 钳到官方上限 1000**（官方 ≤1000/次、≤4000 次/分钟；本仓单轮自我节流
  是另一回事，两个数不许混——方案 §8）。

夹具＝真 RSA-2048 密钥对（cryptography 现生成）＋假 SDK（getChatData 按 seq 过滤、
decryptData 恒等解）＋真 ArchiveProjectionStore（生产 DDL 自建自插，tmp_path）。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import padding

from neurova.channels import wechat_kf_crypto, wecom_archive

#: 被测面一律 wecom_archive.<attr> 懒取：缺席时红在用例体（AttributeError），
#: 不红在整档收集（C7a 夹具纪律）。

# ── 夹具 ─────────────────────────────────────────────────────


class FakeArchiveSdk:
    """假 SDK：getChatData 只返回 seq > 入参的行（官方「从 seq+1 起」语义）；
    decryptData 恒等解（AES 半边在 SDK 内的替身）。记录调用防双重推进。"""

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


def _rsaKeyPair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key, pem, key.public_key()


def _rawRow(seq, plainMsg, publicKey, ver="v1", msgid=None):
    """按官方返回行形状构造密文行：RSA 半边走真实现（公钥封装 random key）。"""
    randomKey = b"0123456789abcdef0123456789abcdef"
    sealed = publicKey.encrypt(randomKey, padding.PKCS1v15())
    return {
        "seq": seq,
        "msgid": msgid or ("msg_%d" % seq),
        "publickey_ver": ver,
        "encrypt_random_key": base64.b64encode(sealed).decode("ascii"),
        "encrypt_chat_msg": base64.b64encode(
            json.dumps(plainMsg, ensure_ascii=False).encode("utf-8")
        ).decode("ascii"),
    }


def _plain(seq, msgtype="text", content="你好", *, action="send", roomid="",
           fromId="userid_a", tolist=None, msgtime=1700000000000, mediaKey=None):
    plain = {
        "msgid": "msg_%d" % seq,
        "action": action,
        "from": fromId,
        "tolist": tolist if tolist is not None else ["userid_b"],
        "roomid": roomid,
        "msgtime": msgtime,
        "msgtype": msgtype,
    }
    if msgtype == "text":
        plain["text"] = {"content": content}
    elif mediaKey:
        plain[msgtype] = {"sdkfileid": mediaKey}
    return plain


@pytest.fixture()
def keyPair():
    return _rsaKeyPair()


@pytest.fixture()
def keyMap(keyPair):
    _priv, pem, _pub = keyPair
    return {"v1": pem}


# ── 拉取语义 ─────────────────────────────────────────────────


def test_pull_passes_seq_verbatim_and_returns_from_seq_plus_one(keyPair, keyMap):
    """入参 seq 原样进 SDK（自增一即双重推进）；官方语义「从 seq+1 起返回」。"""
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1), pub),
        2: _rawRow(2, _plain(2), pub),
        3: _rawRow(3, _plain(3), pub),
    })
    result = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)
    assert sdk.calls == [(0, 10)], "入参 seq 必须原样交 SDK（从 seq+1 起是官方语义）"
    assert [row["seq"] for row in result.rows] == [1, 2, 3]
    assert result.nextSeq == 3
    assert result.hasMore is False


def test_next_seq_takes_max_seen_even_when_rows_skip(keyPair, keyMap):
    """跳过行（未知 key_ver）也推进水位——否则坏版本行会被无限重拉。"""
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1), pub),
        2: _rawRow(2, _plain(2), pub, ver="vUnknown"),
        3: _rawRow(3, _plain(3), pub),
    })
    result = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)
    assert [row["seq"] for row in result.rows] == [1, 3]
    assert result.counts["skipped_unknown_key_ver"] == 1
    assert result.nextSeq == 3


def test_pull_empty_page_keeps_watermark(keyPair, keyMap):
    _priv, _pem, _pub = keyPair
    sdk = FakeArchiveSdk({})
    result = wecom_archive.pullArchiveBatch(sdk, 42, 10, keyMap)
    assert result.rows == []
    assert result.nextSeq == 42, "空页不推水位（拉不到新行＝水位原地）"


def test_limit_clamped_to_official_max(keyPair, keyMap):
    """limit ≤ 1000 是官方上限；钳制在 pull 层，SDK 永远收不到越界值。"""
    _priv, _pem, _pub = keyPair
    sdk = FakeArchiveSdk({})
    wecom_archive.pullArchiveBatch(sdk, 0, 5000, keyMap)
    assert sdk.calls == [(0, wecom_archive.ARCHIVE_BATCH_LIMIT_MAX)]
    assert wecom_archive.ARCHIVE_BATCH_LIMIT_MAX == 1000


def test_rsa_failure_raises_not_silently_archived(keyPair, keyMap):
    """密文与私钥不匹配 → 显式抛（§5），该批整体失败，不落半行密文。"""
    _priv, _pem, pub = keyPair
    _p2, _pem2, pub2 = _rsaKeyPair()
    sdk = FakeArchiveSdk({1: _rawRow(1, _plain(1), pub2, ver="v1")})
    with pytest.raises(ValueError):
        wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)


def test_unknown_key_ver_row_does_not_raise(keyPair, keyMap):
    """未知 publickey_ver：跳过并计数（§3 前置表），不抛不猜。"""
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({1: _rawRow(1, _plain(1), pub, ver="v99")})
    result = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)
    assert result.rows == []
    assert result.counts["skipped_unknown_key_ver"] == 1
    assert result.nextSeq == 1


# ── 归一 ─────────────────────────────────────────────────────


def test_plain_message_normalized_fields(keyPair, keyMap):
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1, roomid="wrJC2cBcAA111", content="群里说"), pub),
    })
    (row,) = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap).rows
    assert row["msgid"] == "msg_1"
    assert row["action"] == "send"
    assert row["msgtype"] == "text"
    assert row["from_id"] == "userid_a"
    assert row["tolist"] == '["userid_b"]'
    assert row["roomid"] == "wrJC2cBcAA111"
    assert row["msgtime_ms"] == 1700000000000
    assert row["text"] == "群里说"
    assert row["media_ref"] == ""


def test_media_msgtype_carries_sdkfileid_only(keyPair, keyMap):
    """非文本类正文列留空、附件列承载 sdkfileid（§5：两种引用形态不同源）。"""
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1, msgtype="image", mediaKey="sdkfileid_IMG_1"), pub),
    })
    (row,) = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap).rows
    assert row["text"] == ""
    assert row["media_ref"] == "sdkfileid_IMG_1"
    assert row["msgtype"] == "image"


def test_unknown_msgtype_counted_and_archived_verbatim(keyPair, keyMap):
    """未知 msgtype 不猜：原样落投影＋计数，text/media 双空。"""
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1, msgtype="striker_card"), pub),
    })
    result = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)
    (row,) = result.rows
    assert row["msgtype"] == "striker_card"
    assert row["text"] == ""
    assert row["media_ref"] == ""
    assert result.counts["unknown_msgtype"] == 1


def test_recall_and_switch_counted(keyPair, keyMap):
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1, action="recall"), pub),
        2: _rawRow(2, _plain(2, action="switch"), pub),
    })
    result = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap)
    assert result.counts["recall"] == 1
    assert result.counts["switch"] == 1
    assert {row["action"] for row in result.rows} == {"recall", "switch"}


def test_msgtime_millis_to_iso():
    """毫秒 → ISO8601 带时区（与捕获面 timestamp.isoformat() 同形）；0＝未知如实空。"""
    assert wecom_archive.msgtimeMillisToIso(1700000000000) == "2023-11-14T22:13:20+00:00"
    assert wecom_archive.msgtimeMillisToIso(0) == ""


# ── 投影落库 ─────────────────────────────────────────────────


def test_append_batch_is_transactional_and_idempotent(tmp_path, keyPair, keyMap):
    _priv, _pem, pub = keyPair
    sdk = FakeArchiveSdk({
        1: _rawRow(1, _plain(1), pub),
        2: _rawRow(2, _plain(2), pub),
    })
    rows = wecom_archive.pullArchiveBatch(sdk, 0, 10, keyMap).rows
    store = wecom_archive.ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        assert store.appendBatch(rows, nextSeq=2) == 2
        assert store.watermark() == 2
        # 重放同批：幂等（INSERT OR IGNORE），written=0、水印不动
        assert store.appendBatch(rows, nextSeq=2) == 0
        assert store.watermark() == 2
    finally:
        store.close()


def test_append_rolls_back_on_bad_row(tmp_path):
    """坏行 → 整批回滚：不落半行、水印不动（§5：拉取失败不落半行）。"""
    store = wecom_archive.ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        good = {
            "seq": 1, "msgid": "m1", "publickey_ver": "v1", "action": "send",
            "msgtype": "text", "from_id": "a", "tolist": "[]", "roomid": "",
            "msgtime_ms": 1, "text": "t", "media_ref": "",
        }
        bad = dict(good, seq="not-an-int", msgid="m2")
        with pytest.raises(Exception):
            store.appendBatch([good, bad], nextSeq=2)
        assert store.watermark() == 0
        assert store.querySendRows(0, 10) == ([], 0, False)
    finally:
        store.close()


def test_sdk_getchatdata_error_raises_archive_sdk_error():
    class BrokenSdk:
        def getChatData(self, seq, limit, timeout=10):
            raise wecom_archive.ArchiveSdkError("GetChatData 失败 ret=5")

        def decryptData(self, encryptKey, encryptMsg):
            return encryptMsg

        def close(self):
            return None

    with pytest.raises(wecom_archive.ArchiveSdkError):
        wecom_archive.pullArchiveBatch(BrokenSdk(), 0, 10, {"v1": b"pem"})
