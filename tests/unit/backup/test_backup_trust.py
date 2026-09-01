# -*- coding: utf-8 -*-
"""
P3-c backup 信任模型核心防回归网（对标 QP beta.5 backup/signing）

语义：把备份 zip 当信任边界——
- 本地实例 key（32 字节，0600 O_EXCL 创建、拒绝 symlink）HMAC 签名
- 签名覆盖 meta 固定字段集 + 全部非 meta zip 条目（确定性排序、流式）
- 验证三态：trusted（本地签名通过）/ foreign（签名不匹配）/ legacy（无签名）
- 信任后重签：外来备份导入即绑定本地决定（resign）
- 篡改检测：任一条目或 meta 被改 → foreign
"""
import io
import json
import zipfile

import pytest

from neurova.backup.trust import (
    BackupTrustError,
    SigningKey,
    TrustMode,
    resign_backup,
    sign_backup,
    verify_backup,
)


@pytest.fixture()
def key_path(tmp_path):
    return tmp_path / "backups" / ".signing_key"


@pytest.fixture()
def key(key_path):
    return SigningKey(key_path)


def _mk_zip(path, entries: dict, meta: dict = None):
    meta = meta or {"scheme": "hmac-sha256-v1", "created_at": "2026-09-01T00:00:00", "backup_id": "b1"}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(entries):
            zf.writestr(name, entries[name])
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return path


class TestSigningKey:
    def test_create_atomic_0600(self, key):
        assert len(key.key_bytes) == 32
        # 第二次加载同一文件：同一把 key
        key2 = SigningKey(key.path)
        assert key2.key_bytes == key.key_bytes

    def test_reject_symlink(self, key_path, tmp_path):
        import os

        real = tmp_path / "real.key"
        real.write_bytes(b"x" * 32)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(real, key_path)
        with pytest.raises(BackupTrustError, match="symlink"):
            SigningKey(key_path)


class TestSignVerify:
    def test_sign_then_verify_trusted(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b1.zip", {"sessions/a.json": "{}", "kb/x.txt": "hello"})
        sign_backup(zp, key)
        verdict = verify_backup(zp, key)
        assert verdict.mode == TrustMode.TRUSTED

    def test_unsigned_is_legacy(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b2.zip", {"a.txt": "x"})
        verdict = verify_backup(zp, key)
        assert verdict.mode == TrustMode.LEGACY

    def test_tampered_entry_is_foreign(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b3.zip", {"a.txt": "x"})
        sign_backup(zp, key)
        # 篡改一个条目（重建 zip）
        with zipfile.ZipFile(zp, "r") as zf:
            names = zf.namelist()
            data = {n: zf.read(n) for n in names}
        data["a.txt"] = "tampered"
        tampered = tmp_path / "b3-tampered.zip"
        meta = json.loads(data.pop("meta.json"))
        with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zf:
            for n in sorted(data):
                zf.writestr(n, data[n])
            zf.writestr("meta.json", json.dumps(meta))
        verdict = verify_backup(tampered, key)
        assert verdict.mode == TrustMode.FOREIGN

    def test_tampered_meta_is_foreign(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b4.zip", {"a.txt": "x"})
        sign_backup(zp, key)
        with zipfile.ZipFile(zp, "r") as zf:
            data = {n: zf.read(n) for n in zf.namelist()}
        meta = json.loads(data["meta.json"])
        meta["backup_id"] = "forged"
        data["meta.json"] = json.dumps(meta, ensure_ascii=False, indent=2)
        forged = tmp_path / "b4-forged.zip"
        with zipfile.ZipFile(forged, "w", zipfile.ZIP_DEFLATED) as zf:
            for n in sorted(data):
                zf.writestr(n, data[n])
        assert verify_backup(forged, key).mode == TrustMode.FOREIGN

    def test_other_key_is_foreign(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b5.zip", {"a.txt": "x"})
        sign_backup(zp, key)
        other = SigningKey(tmp_path / "other" / ".signing_key")
        assert verify_backup(zp, other).mode == TrustMode.FOREIGN

    def test_resign_binds_local_decision(self, key, tmp_path):
        """外来备份显式信任（foreign → resign）后变 trusted"""
        zp = _mk_zip(tmp_path / "b6.zip", {"a.txt": "imported"})
        assert verify_backup(zp, key).mode == TrustMode.LEGACY  # 无签名
        resign_backup(zp, key)
        assert verify_backup(zp, key).mode == TrustMode.TRUSTED

    def test_signature_in_meta_with_scheme(self, key, tmp_path):
        zp = _mk_zip(tmp_path / "b7.zip", {"a.txt": "x"})
        sign_backup(zp, key)
        with zipfile.ZipFile(zp) as zf:
            meta = json.loads(zf.read("meta.json"))
        assert meta["signature"].startswith("hmac-sha256-v1:")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
