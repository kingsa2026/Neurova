"""files store SQLite 持久化单元测试。

锁定契约：
- persist_file / delete_file_record：写穿 files 表（data/users.db 同库新表）；
- hydrate_files_store：启动水合——磁盘文件仍在的行恢复进 _files_store，
  磁盘文件已丢的行自动清理（防 404 僵尸元数据）。
"""

import tempfile
import unittest
from pathlib import Path

from neurova.api.endpoints import files_api


class TestFilesStorePersistence(unittest.TestCase):
    def setUp(self):
        files_api._files_store.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "users.db")
        self.addCleanup(self.tmp.cleanup)

    def _make_record(self, file_id: str, real_file: bool = True) -> dict:
        path = Path(self.tmp.name) / f"{file_id}_a.txt"
        if real_file:
            path.write_text("content", encoding="utf-8")
        return {
            "file_id": file_id,
            "filename": "a.txt",
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 7,
            "version": "1.0.0",
            "status": "active",
            "user_id": "u1",
            "agent_id": "default",
            "path": str(path),
            "created_at": 1.0,
            "updated_at": 1.0,
        }

    def test_persist_and_hydrate_roundtrip(self):
        rec = self._make_record("f1")
        files_api._files_store["f1"] = rec
        files_api.persist_file("f1", rec, db_path=self.db_path)

        files_api._files_store.clear()
        loaded = files_api.hydrate_files_store(db_path=self.db_path)
        self.assertIn("f1", loaded)
        self.assertEqual(loaded["f1"]["filename"], "a.txt")
        self.assertIn("f1", files_api._files_store)

    def test_hydrate_drops_rows_with_missing_disk_file(self):
        rec = self._make_record("f2", real_file=False)
        files_api.persist_file("f2", rec, db_path=self.db_path)
        loaded = files_api.hydrate_files_store(db_path=self.db_path)
        self.assertNotIn("f2", loaded)

    def test_delete_record_removes_row(self):
        rec = self._make_record("f3")
        files_api.persist_file("f3", rec, db_path=self.db_path)
        files_api.delete_file_record("f3", db_path=self.db_path)
        loaded = files_api.hydrate_files_store(db_path=self.db_path)
        self.assertNotIn("f3", loaded)

    def test_corrupt_db_does_not_raise(self):
        p = Path(self.tmp.name) / "corrupt.db"
        p.write_bytes(b"not a sqlite db")
        # 水合遇坏库应静默返回空（不阻塞启动）
        loaded = files_api.hydrate_files_store(db_path=str(p))
        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
