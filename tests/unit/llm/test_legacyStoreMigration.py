# -*- coding: utf-8 -*-
"""P2-22 收尾：旧单文件密钥库 → default 桶 一次性幂等迁移（红→绿）

旧 ``providers/secret_store.py`` 的全局密钥库落盘为单文件 ``secrets.json``，条目值是
三种历史形态之一：``enc:v2:`` 密文串、历史 ``enc:`` XOR 弱密文串、``{"value": ...}``
包装对象（内嵌密文 + 零散元数据）。本批把全局库统一迁入 clean 版 default 桶
（旧文件同级的 ``secrets/`` 桶目录，三件套布局）：

- ``enc:v2:`` 密文与 clean 同源同格式 → 验解后原样直搬（不重加密）；
- 其余形态解到明文后按 clean 加密口径（AES-256-GCM）重新封装；
- metadata/access_log 置初值；
- 迁移后旧文件改名 ``secrets.json.retired-<时间戳>`` 隔离保留，旧文件不在原名即
  不再触发（幂等）；
- 损坏条目跳过并 warning 点名，任何意外回落原单文件路径，不阻断启动。
"""

import base64
import hashlib
import json
import logging
from pathlib import Path

import neurova.llm.providers.secret_store_clean as cleanModule
from neurova.llm.providers.secret_store_clean import (
    SecretStore,
    decrypt_api_key,
    encrypt_api_key,
    migrateLegacyFileStore,
)

_MASTER_KEY = "migration-master-key-2026"

# 迁移后应进 default 桶的条目 → 期望明文
_PLAINTEXTS = {
    "provider_openai": "sk-openai-plain",
    "neurflow_store_1": "sk-store-plain",
    "oauth_state_x": "oauth-state-plain",
    "build_session_q": "build-answer-plain",
}
# 应被跳过的损坏条目（fail-soft 点名，不阻断）
_SKIPPED = ["corrupt_b64", "corrupt_wrongtype", "foreign_key_v2"]


def _legacyXorCipher(value: str, key: str) -> str:
    """旧版 XOR 写格式的存量预言机：``enc:`` + base64(0x01 + 明文 XOR 派生密钥流)。

    与 ``decrypt_api_key`` 的遗留只读解码路径互为逆运算，不依赖仓内私有函数。
    """
    derived = hashlib.sha256(
        b"neurova-secret-store-v1" + key.encode("utf-8") + b"|neurova|secret|v1"
    ).digest()
    payload = bytes([0x01]) + value.encode("utf-8")
    xored = bytes(b ^ derived[i % len(derived)] for i, b in enumerate(payload))
    return "enc:" + base64.b64encode(xored).decode("ascii")


def _legacyEntries() -> dict:
    """一份覆盖全部历史形态 + 损坏形态的旧单文件库内容。"""
    return {
        # 裸 enc:v2: 串：与 clean 同源，应验解后原样直搬
        "provider_openai": encrypt_api_key(_PLAINTEXTS["provider_openai"], _MASTER_KEY),
        # {"value": ...} 包装 + 旧 XOR 内芯：解包后按 clean 口径重新封装
        "neurflow_store_1": {
            "value": _legacyXorCipher(_PLAINTEXTS["neurflow_store_1"], _MASTER_KEY),
            "updated_at": "2026-11-01T00:00:00",
            "id": "sec_legacy1",
        },
        # {"value": ...} 包装 + v2 内芯：解包后密文可解，直搬
        "oauth_state_x": {
            "value": encrypt_api_key(_PLAINTEXTS["oauth_state_x"], _MASTER_KEY)
        },
        # 裸旧 XOR 串：按 clean 口径重新封装
        "build_session_q": _legacyXorCipher(_PLAINTEXTS["build_session_q"], _MASTER_KEY),
        # 损坏：前缀对但 base64 不合法
        "corrupt_b64": "enc:%%%not-base64%%%",
        # 损坏：值类型不对
        "corrupt_wrongtype": 12345,
        # 密钥不同源的 v2 密文：解不开，按损坏跳过
        "foreign_key_v2": encrypt_api_key("other-key-secret", "another-master-key"),
    }


def _migrate(root: Path, entries: dict) -> str:
    """在 root 下预置旧单文件库并触发一次迁移，返回迁移函数的落点。"""
    legacy = root / "secrets.json"
    legacy.write_text(json.dumps(entries), encoding="utf-8")
    return migrateLegacyFileStore(str(legacy), masterKey=_MASTER_KEY)


def testLegacyEntriesMigrateIntoDefaultBucketAndStayDecryptable(tmp_path):
    """旧条目进 default 桶、全部为 clean v2 密文且可解密；旧文件退役留档。"""
    entries = _legacyEntries()
    bucketPath = _migrate(tmp_path, entries)

    bucketFile = tmp_path / "secrets" / "secrets.json"
    assert Path(bucketPath) == bucketFile, "迁移后全局库应落在 default 桶的 secrets.json"

    stored = json.loads(bucketFile.read_text(encoding="utf-8"))
    assert set(stored) == set(_PLAINTEXTS), f"应只导入可解密条目，盘上为: {sorted(stored)}"
    assert all(v.startswith("enc:v2:") for v in stored.values()), (
        "迁移后必须全部是 clean 认证加密格式（enc:v2:）"
    )
    assert stored["provider_openai"] == entries["provider_openai"], (
        "v2 密文与 clean 同源，应原样直搬而不是重加密"
    )
    for name, plain in _PLAINTEXTS.items():
        assert decrypt_api_key(stored[name], master_key=_MASTER_KEY) == plain, (
            f"{name} 迁移后必须可解密回原明文"
        )

    metadata = json.loads(
        (tmp_path / "secrets" / "metadata.json").read_text(encoding="utf-8")
    )
    assert set(metadata) == set(_PLAINTEXTS), "metadata 应为导入条目置初值"
    for name, meta in metadata.items():
        assert meta["name"] == name
        assert meta["access_count"] == 0 and meta["rotation_count"] == 0
        assert meta["tags"] == []
    accessLog = json.loads(
        (tmp_path / "secrets" / "access_log.json").read_text(encoding="utf-8")
    )
    assert accessLog == [], "access_log 应置初值为空列表"

    assert not (tmp_path / "secrets.json").exists(), "旧单文件迁移后必须退役改名"
    retired = list(tmp_path.glob("secrets.json.retired-*"))
    assert len(retired) == 1, f"旧文件应恰好留一份退役档，实得 {[p.name for p in retired]}"
    assert json.loads(retired[0].read_text(encoding="utf-8")) == entries, (
        "退役档必须原样保留旧数据（隔离保留，不删除）"
    )


def testCleanStoreReadsMigratedEntriesFromBucket(tmp_path):
    """迁移产物必须能被 clean 单文件库直接打开并读回明文（接线闭环）。"""
    bucketPath = _migrate(tmp_path, _legacyEntries())
    store = SecretStore(master_key=_MASTER_KEY, storage_path=bucketPath)

    for name, plain in _PLAINTEXTS.items():
        assert store.get(name) == plain, f"{name} 经 clean 库必须读得回明文"
    assert set(store.list_keys()) == set(_PLAINTEXTS)
    assert store.count() == len(_PLAINTEXTS)
    assert store.has("oauth_state_x")
    assert not store.has("corrupt_b64"), "损坏条目不得被搬进新库"


def testGetSecretStoreMigratesOnceAndStaysIdempotent(tmp_path, monkeypatch):
    """get_secret_store 首次构建触发迁移；二次构建不重复迁移（桶内容与退役档数量不变）。"""
    legacy = tmp_path / "secrets.json"
    entries = _legacyEntries()
    legacy.write_text(json.dumps(entries), encoding="utf-8")

    def _fakeConfigGet(key, default=""):
        return {
            "NEUROVA_MASTER_KEY": _MASTER_KEY,
            "NEUROVA_SECRETS_PATH": str(legacy),
        }.get(key, default)

    monkeypatch.setattr(cleanModule.config, "get", _fakeConfigGet)
    monkeypatch.setattr(cleanModule, "_singleton", None)
    try:
        store = cleanModule.get_secret_store()
        assert store.get("neurflow_store_1") == _PLAINTEXTS["neurflow_store_1"], (
            "首次构建应完成迁移且读得回旧凭据"
        )
        assert not legacy.exists(), "首次构建后旧单文件应已退役改名"

        bucketFile = tmp_path / "secrets" / "secrets.json"
        snapshot = bucketFile.read_bytes()
        retiredCount = len(list(tmp_path.glob("secrets.json.retired-*")))

        cleanModule._reset_singleton_for_tests()
        store2 = cleanModule.get_secret_store()
        assert store2.get("build_session_q") == _PLAINTEXTS["build_session_q"], (
            "二次构建必须继续读得回旧凭据"
        )
        assert len(list(tmp_path.glob("secrets.json.retired-*"))) == retiredCount, (
            "二次构建不得重复迁移：退役档数量不应增多"
        )
        assert bucketFile.read_bytes() == snapshot, (
            "二次构建不得改写 default 桶内容"
        )
    finally:
        cleanModule._reset_singleton_for_tests()


def testCorruptEntriesAreSkippedAndNamedWithoutBlocking(tmp_path, caplog):
    """损坏条目逐条跳过并 warning 点名，可解密条目照常导入，整个过程不抛异常。"""
    with caplog.at_level(logging.WARNING):
        bucketPath = _migrate(tmp_path, _legacyEntries())

    stored = json.loads(Path(bucketPath).read_text(encoding="utf-8"))
    assert set(stored) == set(_PLAINTEXTS), "损坏条目之外的可解密条目必须照常导入"
    for skipped in _SKIPPED:
        assert skipped in caplog.text, f"损坏条目 {skipped} 必须 warning 点名"


def testUnparseableLegacyFileIsRetiredNotImported(tmp_path):
    """旧文件整体不是 JSON 时：不导入（按空库），仍退役留档，不阻断启动。"""
    legacy = tmp_path / "secrets.json"
    legacy.write_text("{not json at all", encoding="utf-8")

    bucketPath = migrateLegacyFileStore(str(legacy), masterKey=_MASTER_KEY)

    assert Path(bucketPath) == tmp_path / "secrets" / "secrets.json"
    stored = json.loads(
        (tmp_path / "secrets" / "secrets.json").read_text(encoding="utf-8")
    )
    assert stored == {}, "不可解析的旧库不得导入任何条目"
    assert not legacy.exists(), "不可解析的旧库也应退役改名"
    retired = list(tmp_path.glob("secrets.json.retired-*"))
    assert len(retired) == 1
    assert retired[0].read_text(encoding="utf-8") == "{not json at all", (
        "退役档必须原样保留（含损坏内容，供事后取证）"
    )


def testMissingCryptoLeavesLegacyStoreUntouched(tmp_path, monkeypatch):
    """认证加密依赖缺失时暂缓迁移：不动旧文件、不建桶，沿用原单文件路径。"""
    legacy = tmp_path / "secrets.json"
    entries = _legacyEntries()
    raw = json.dumps(entries)
    legacy.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(cleanModule, "HAS_CRYPTO", False)

    bucketPath = migrateLegacyFileStore(str(legacy), masterKey=_MASTER_KEY)

    assert Path(bucketPath) == legacy, "无认证加密能力时不得迁移，继续沿用原单文件"
    assert legacy.read_text(encoding="utf-8") == raw, "暂缓迁移不得改写旧文件"
    assert not (tmp_path / "secrets").exists(), "暂缓迁移不得创建 default 桶"


class _boomMeta:
    """替身：构造正常但 to_dict 必炸，模拟迁移写 metadata 环节的意外故障。"""

    def __init__(self, name):
        self.name = name

    def to_dict(self):
        raise RuntimeError("boom")


def testUnexpectedMigrationFailureFallsBackToLegacyPath(tmp_path, monkeypatch):
    """迁移中途的意外故障必须 fail-soft：回落原单文件路径，旧文件原样在场，不阻断启动。"""
    legacy = tmp_path / "secrets.json"
    entries = {"provider_openai": encrypt_api_key(_PLAINTEXTS["provider_openai"], _MASTER_KEY)}
    legacy.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(cleanModule, "SecretMetadata", _boomMeta)

    bucketPath = migrateLegacyFileStore(str(legacy), masterKey=_MASTER_KEY)

    assert Path(bucketPath) == legacy, "迁移意外失败必须回落原单文件路径"
    assert legacy.exists(), "回落时旧文件必须原样在场（数据不丢）"
    store = SecretStore(master_key=_MASTER_KEY, storage_path=str(legacy))
    assert store.get("provider_openai") == _PLAINTEXTS["provider_openai"], (
        "回落路径上的旧库必须仍能被 clean 库正常打开读取"
    )
