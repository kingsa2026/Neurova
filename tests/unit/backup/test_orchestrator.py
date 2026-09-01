# -*- coding: utf-8 -*-
"""
遗留② backup 编排层防回归网：create / restore / import 走信任模型

- BackupOrchestrator.create_backup(sources, out_dir, key)：打包 → 签名 →
  产物 zip 的 meta 带 signature
- restore_backup(zip, key, apply_fn)：先 verify → TRUSTED 才 apply；
  FOREIGN 拒绝（篡改/他实例）；LEGACY 需显式 trust=True
- import_backup(zip, key, trust_mode)：foreign/legacy 显式信任后 resign
"""
import json
import zipfile

import pytest

from neurova.backup.orchestrator import (
    BackupOrchestrator,
    TrustRequiredError,
)
from neurova.backup.trust import SigningKey, TrustMode


@pytest.fixture()
def orch(tmp_path):
    key = SigningKey(tmp_path / "keys" / ".signing_key")
    return BackupOrchestrator(key=key, work_dir=tmp_path / "work")


class TestCreateBackup:
    def test_create_produces_signed_zip(self, orch, tmp_path):
        src = tmp_path / "src"
        (src / "sessions").mkdir(parents=True)
        (src / "sessions" / "a.json").write_text("{}", encoding="utf-8")
        (src / "kb").mkdir()
        (src / "kb" / "notes.md").write_text("# n", encoding="utf-8")

        out = orch.create_backup({"sessions": src / "sessions", "kb": src / "kb"})
        assert out.exists()

        from neurova.backup.trust import verify_backup

        assert verify_backup(out, orch.key).mode == TrustMode.TRUSTED
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "sessions/a.json" in names and "kb/notes.md" in names
            meta = json.loads(zf.read("meta.json"))
            assert meta["backup_id"].startswith("nvbak-")

    def test_backup_id_unique(self, orch, tmp_path):
        src = tmp_path / "s"
        src.mkdir()
        (src / "f.txt").write_text("x", encoding="utf-8")
        ids = [orch.create_backup({"data": src}).name for _ in range(2)]
        assert ids[0] != ids[1]


class TestRestoreBackup:
    def test_trusted_restores(self, orch, tmp_path):
        src = tmp_path / "s"
        src.mkdir()
        (src / "a.txt").write_text("content-v1", encoding="utf-8")
        out = orch.create_backup({"data": src})

        # 目标目录预写不同内容
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "a.txt").write_text("old", encoding="utf-8")

        applied = {}
        result = orch.restore_backup(out, apply_fn=lambda payload: applied.update(payload))
        assert result["mode"] == TrustMode.TRUSTED
        assert applied["files"]["data/a.txt"] == "content-v1"

    def test_foreign_rejected_without_force(self, orch, tmp_path):
        src = tmp_path / "s"
        src.mkdir()
        (src / "a.txt").write_text("x", encoding="utf-8")
        out = orch.create_backup({"data": src})

        # 用另一把 key 验证 → FOREIGN
        other = SigningKey(tmp_path / "other" / ".signing_key")

        def boom(payload):
            raise AssertionError("FOREIGN 备份绝不应被 apply")

        with pytest.raises(TrustRequiredError):
            orch.restore_backup(out, apply_fn=boom, key=other)

    def test_legacy_requires_explicit_trust(self, orch, tmp_path):
        # 无签名 zip
        legacy = tmp_path / "legacy.zip"
        with zipfile.ZipFile(legacy, "w") as zf:
            zf.writestr("data/a.txt", "legacy-content")
            zf.writestr("meta.json", json.dumps({"backup_id": "old"}))

        def boom(payload):
            raise AssertionError("legacy 未显式信任不应 apply")

        with pytest.raises(TrustRequiredError):
            orch.restore_backup(legacy, apply_fn=boom)

        # 显式信任 → 放行
        applied = {}
        result = orch.restore_backup(legacy, apply_fn=lambda p: applied.update(p), trust=True)
        assert result["mode"] == TrustMode.LEGACY
        assert applied["files"]["data/a.txt"] == "legacy-content"

    def test_apply_failure_rolls_back_via_checkpoint_semantics(self, orch, tmp_path):
        """apply_fn 失败 → TrustRequiredError 不吞（编排层不重复实现回滚，
        回滚由调用方用 restore_with_rollback 组合）"""
        src = tmp_path / "s"
        src.mkdir()
        (src / "a.txt").write_text("x", encoding="utf-8")
        out = orch.create_backup({"data": src})

        def failing(payload):
            raise RuntimeError("apply boom")

        with pytest.raises(RuntimeError):
            orch.restore_backup(out, apply_fn=failing)


class TestImportBackup:
    def test_import_resigns(self, orch, tmp_path):
        # 外部实例签名
        foreign_key = SigningKey(tmp_path / "foreign" / ".signing_key")
        src = tmp_path / "s"
        src.mkdir()
        (src / "a.txt").write_text("imported", encoding="utf-8")

        from neurova.backup.trust import sign_backup

        zp = tmp_path / "foreign.zip"
        _mk_simple_zip(zp, {"data/a.txt": "imported"})
        sign_backup(zp, foreign_key)

        # 他实例签名的备份 → FOREIGN，显式 trust=True 后导入并本地重签
        imported = orch.import_backup(zp, trust=True)
        from neurova.backup.trust import verify_backup

        assert verify_backup(imported, orch.key).mode == TrustMode.TRUSTED

    def test_import_legacy_requires_trust(self, orch, tmp_path):
        zp = tmp_path / "legacy.zip"
        _mk_simple_zip(zp, {"a.txt": "old-format"})

        with pytest.raises(TrustRequiredError):
            orch.import_backup(zp)  # legacy 未显式信任

        imported = orch.import_backup(zp, trust=True)
        from neurova.backup.trust import verify_backup

        assert verify_backup(imported, orch.key).mode == TrustMode.TRUSTED


def _mk_simple_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in sorted(entries):
            zf.writestr(n, entries[n])
        zf.writestr("meta.json", json.dumps({"backup_id": "old-1"}))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
