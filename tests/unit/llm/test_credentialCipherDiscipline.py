"""P0-3：`secret_store_clean` 的凭据加密必须是认证加密，且不得静默丢数据（红→绿）

现状（读码 + 本文件红灯实测）：
- `SimpleCipher` 是**重复密钥流 XOR**：keystream = `sha256(key)` 循环复用。两条不同
  凭据的密文按位异或即得两条明文的异或（无认证、无 IV、无完整性）；
- 篡改密文任意一位**不会报错**，只会解出垃圾并当作明文交给调用方
  （`web_reach/credentials` → SSH 主机凭据、社交平台凭据都走这条路）；
- `_load_secrets()` 解不开时只 `logger.warning` 后**丢弃该条**，而 `_save_secrets()`
  从内存重写整个 `secrets.json` → 一次换密钥/一次损坏就让存量凭据**静默消失**，
  而 `store_secret()` 照样回 True；
- pycryptodome 缺失时（`providers/secret_store.HAS_CRYPTO=False`）本模块毫无察觉，
  照旧写 XOR——降级门开着且不点名。

处置口径：仓内已有唯一认证加密实现（`providers/secret_store.py` 的 `enc:v2:`
AES-256-GCM，per-record 随机 salt+nonce），写侧必须走它，不新造第二套密码学；
本模块历史格式只保留**只读**遗留解码并在下次落盘时自动升级。
"""

import base64
import hashlib
import json
from pathlib import Path

import neurova.llm.providers.secret_store_clean as cleanModule
from neurova.llm.providers.secret_store_clean import SecretStore

LEGACY_NAME = "legacy_token"
LEGACY_VALUE = "sk-legacy-abcdef-0123456789"


def legacyCiphertext(value: str, key: str) -> str:
    """历史写入格式（存量预言机）：base64(value XOR sha256(key))。"""
    keystream = hashlib.sha256(key.encode("utf-8")).digest()
    xored = bytes(b ^ keystream[i % len(keystream)] for i, b in enumerate(value.encode("utf-8")))
    return base64.b64encode(xored).decode("ascii")


def _seedLegacyBucket(root: Path, value: str = LEGACY_VALUE, key: str = "k1") -> Path:
    """按历史格式预置一个凭据桶（模拟升级前留下的存量密文）。"""
    bucket = root / "bucket"
    bucket.mkdir(parents=True, exist_ok=True)
    (bucket / "secrets.json").write_text(
        json.dumps({LEGACY_NAME: legacyCiphertext(value, key)}), encoding="utf-8"
    )
    return bucket


def _rawStored(bucket: Path) -> dict:
    return json.loads((bucket / "secrets.json").read_text(encoding="utf-8"))


def testNewWritesUseAuthenticatedCipher(tmp_path):
    """新写入必须是认证加密格式（enc:v2:），不得再落重复密钥流 XOR。"""
    bucket = tmp_path / "bucket"
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")

    assert store.store_secret("fresh", "value-fresh") is True

    raw = _rawStored(bucket)["fresh"]
    assert raw.startswith("enc:v2:"), (
        f"新凭据仍写成 {raw[:24]}…——重复密钥流 XOR 无任何完整性保护"
    )


def testLegacyCiphertextReadsBackAndIsUpgradedOnLoad(tmp_path):
    """存量 XOR 密文必须读得回，并且**只是打开**就被换成认证格式（不等下次写）。"""
    bucket = _seedLegacyBucket(tmp_path)
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")

    assert store.get_secret(LEGACY_NAME) == LEGACY_VALUE, "存量凭据读不回来——升级即断供"

    raw = _rawStored(bucket)[LEGACY_NAME]
    assert raw.startswith("enc:v2:"), "存量弱密文还躺在盘上——读到时就该换掉，不能等下一次写入"


def testTamperedCiphertextIsNotPassedOffAsPlaintext(tmp_path, caplog):
    """认证加密的价值就在篡改必查：改动密文一位必须被叫出来，不能吐出假明文。"""
    import logging

    bucket = tmp_path / "bucket"
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")
    store.store_secret("api_key", "value-to-tamper")

    data = _rawStored(bucket)
    flipped = list(data["api_key"])
    tailIndex = len(flipped) - 5
    flipped[tailIndex] = "A" if flipped[tailIndex] != "A" else "B"
    data["api_key"] = "".join(flipped)
    (bucket / "secrets.json").write_text(json.dumps(data), encoding="utf-8")

    reopened = SecretStore(storage_path=str(bucket), encryption_key="k1")
    with caplog.at_level(logging.WARNING):
        leaked = reopened.get_secret("api_key")

    assert leaked is None, f"篡改过的密文被当作明文返回：{leaked!r}"
    assert "api_key" in caplog.text, "认证失败必须点名是哪条凭据"


def testUndecryptableEntrySurvivesNextSave(tmp_path):
    """解不开的条目不得被下一次保存抹掉——静默丢凭据比红更危险。"""
    bucket = _seedLegacyBucket(tmp_path)

    # 换钥匙打开：历史条目解不开（模拟密钥轮换/损坏），此时只应标记不可读
    store = SecretStore(storage_path=str(bucket), encryption_key="k2")
    store.store_secret("fresh", "value-fresh")

    raw = _rawStored(bucket)
    assert LEGACY_NAME in raw, (
        "解不开的存量条目被 _save_secrets 从盘上抹掉了——store_secret 还回了 True"
    )
    assert raw[LEGACY_NAME] == legacyCiphertext(LEGACY_VALUE, "k1"), "原文不得被改写"


def testMissingCryptoDependencyDoesNotQuietlyWriteXor(tmp_path, monkeypatch):
    """认证加密依赖缺失时必须失败并点名，不得回落到弱加密照写。"""
    monkeypatch.setattr("neurova.llm.providers.secret_store.HAS_CRYPTO", False)
    bucket = tmp_path / "bucket"
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")

    assert store.store_secret("fresh", "value-fresh") is False, (
        "依赖缺失却报存储成功——写下去的是无认证 XOR"
    )
    raw = _rawStored(bucket) if (bucket / "secrets.json").exists() else {}
    assert all(v.startswith("enc:v2:") for v in raw.values()), f"盘上出现了弱密文：{raw}"


def testWeakCipherAndDeadSingletonRetired():
    """防回流：XOR 加密器与"随机临时密钥 + 零消费者"的全局单例都必须消失。"""
    assert not hasattr(cleanModule, "SimpleCipher"), (
        "SimpleCipher 回来了——重复密钥流 XOR 不得再作为写路径"
    )
    assert not hasattr(cleanModule, "get_secret_store"), (
        "get_secret_store() 无参构造用的是随机临时密钥，写出的密文下个进程解不开；"
        "全仓零消费者，按断点退役"
    )


def testReadingASecretDoesNotReEncryptTheWholeBucket(tmp_path):
    """只读一条凭据不得触发整桶重加密。

    认证加密每条都要 PBKDF2 20 万次迭代（实测 ≈40ms/条），而读路径原本只是为了
    把 `last_accessed`/`access_count` 落盘就顺手重写了 `secrets.json`——换成认证
    加密后，这变成"每读一次凭据，KDF × 桶内条目数"。计数仍要落盘，但只该写侧文件。
    """
    bucket = tmp_path / "bucket"
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")
    store.store_secret("a", "value-a")
    store.store_secret("b", "value-b")

    before = _rawStored(bucket)
    assert store.get_secret("a") == "value-a"

    assert _rawStored(bucket) == before, "读凭据重写了密文——每次读都要为整桶付 KDF 代价"
    assert store.get_metadata("a")["access_count"] == 1, "计数仍须落盘，不能顺手丢掉审计面"


def testUpgradeFailureLeavesExistingCiphertextIntact(tmp_path, monkeypatch):
    """升级失败时盘上原文必须一字不动——失败的写法比不写更危险。"""
    bucket = _seedLegacyBucket(tmp_path)
    before = _rawStored(bucket)

    monkeypatch.setattr("neurova.llm.providers.secret_store.HAS_CRYPTO", False)
    store = SecretStore(storage_path=str(bucket), encryption_key="k1")

    assert _rawStored(bucket) == before, "升级失败却改写了盘——存量凭据自此不可恢复"
    assert store.get_secret(LEGACY_NAME) == LEGACY_VALUE, (
        "历史 XOR 解码不依赖 pycryptodome，读回不受升级失败影响"
    )
